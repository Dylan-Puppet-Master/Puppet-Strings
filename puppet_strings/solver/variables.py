"""Assignment variables: one boolean per (staff, activity, role, block) on the target date.

Every variable carries a time interval inside its block. A clinic position fills the block;
an ad hoc task has a movable start and a variable length, so `FOR 30m` can take part of a
block. Past dates come from Published Schedules and are looked up as plain values.
"""

from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from puppet_strings.model import Activity, Block, Dataset

Literal = cp_model.IntVar | bool


@dataclass(frozen=True)
class Slot:
    """The key of one assignment variable on the target date."""

    staff: str
    activity: str
    role: str | None
    block: str


@dataclass(frozen=True)
class Interval:
    """When an assignment happens, in minutes after midnight. Constants for whole blocks."""

    start: cp_model.IntVar | int
    size: cp_model.IntVar | int
    end: cp_model.IntVar | int
    interval: cp_model.IntervalVar
    block: Block

    @property
    def partial(self) -> bool:
        """Whether the task may take part of the block."""
        return not isinstance(self.size, int)


@dataclass
class Instance:
    """One run of a clinic on the target date, spanning one block or two for (DBL)."""

    activity: Activity
    blocks: tuple[str, ...]
    filled: cp_model.IntVar
    holders: dict[str, dict[str, cp_model.IntVar]] = field(default_factory=dict)
    trainees: dict[str, tuple[str, cp_model.IntVar]] = field(default_factory=dict)


class Variables:
    """Creates and looks up assignment variables, on demand, for a Dataset."""

    def __init__(self, model: cp_model.CpModel, dataset: Dataset) -> None:
        self.model = model
        self.dataset = dataset
        self.x: dict[Slot, cp_model.IntVar] = {}
        self.intervals: dict[Slot, Interval] = {}
        self.sources: dict[Slot, str] = {}
        self.instances: dict[tuple[str, str], Instance] = {}
        self.free_literals: dict[tuple[str, str], cp_model.IntVar] = {}
        self._past: dict[date, dict[tuple[str, str, str | None, str], int]] = {
            day: {(a.staff, a.activity, a.role, a.block): a.minutes for a in rows}
            for day, rows in dataset.published.items()
        }

    # -- creation ---------------------------------------------------------------------

    def instance(self, activity_id: str, blocks: tuple[str, ...], source: str) -> Instance:
        """The instance of an activity in these blocks, created with its position holders."""
        if (activity_id, blocks[0]) in self.instances:
            return self.instances[activity_id, blocks[0]]
        activity = self.dataset.activities[activity_id]
        filled = self.model.NewBoolVar(f"filled:{activity_id}:{blocks[0]}")
        instance = Instance(activity, blocks, filled)
        for position in activity.positions:
            holders = instance.holders[position.role] = {}
            for member in self.dataset.staff.values():
                if not member.available or member.ral < position.ral:
                    continue
                if not member.status(position.skill).eligible:
                    continue
                var = self.model.NewBoolVar(f"x:{member.id}:{activity_id}:{position.role}")
                holders[member.id] = var
                self._register(member.id, activity_id, position.role, blocks, var, source)
        for block in blocks:
            self.instances[activity_id, block] = instance
        return instance

    def trainee(self, staff_id: str, activity_id: str, block: str, source: str) -> Literal:
        """The trainee variable for a staff member on an instance; False if no instance."""
        instance = self.instances.get((activity_id, block))
        if instance is None:
            return False
        if staff_id in instance.trainees:
            return instance.trainees[staff_id][1]
        skill = instance.activity.positions[0].skill if instance.activity.positions else None
        role = self.dataset.staff[staff_id].status(skill).trainee_role
        var = self.model.NewBoolVar(f"x:{staff_id}:{activity_id}:{role}")
        instance.trainees[staff_id] = (role, var)
        self._register(staff_id, activity_id, role, instance.blocks, var, source)
        return var

    def adhoc(self, staff_id: str, text: str, block: str, source: str) -> cp_model.IntVar:
        """The variable for a staff member doing an ad hoc task in a block."""
        slot = Slot(staff_id, text, None, block)
        if slot not in self.x:
            var = self.model.NewBoolVar(f"x:{staff_id}:{text}:{block}")
            self._register(staff_id, text, None, (block,), var, source, partial=True)
        return self.x[slot]

    def adhoc_interval(self, staff_id: str, text: str, block: str, source: str) -> Interval:
        """The interval of an ad hoc task, creating the variable if needed."""
        self.adhoc(staff_id, text, block, source)
        return self.intervals[Slot(staff_id, text, None, block)]

    def free(self, staff_id: str, block: str) -> cp_model.IntVar:
        """True iff the staff member has nothing overlapping this block. Linked in finish()."""
        key = (staff_id, block)
        if key not in self.free_literals:
            self.free_literals[key] = self.model.NewBoolVar(f"free:{staff_id}:{block}")
        return self.free_literals[key]

    def _register(self, staff_id, activity_id, role, blocks, var, source, partial=False):
        for block in blocks:
            slot = Slot(staff_id, activity_id, role, block)
            self.x[slot] = var
            self.sources[slot] = source
            self.intervals[slot] = self._interval(slot, var, partial)

    def _interval(self, slot: Slot, var: cp_model.IntVar, partial: bool) -> Interval:
        block = self.dataset.blocks[slot.block]
        name = f"{slot.staff}:{slot.activity}:{slot.block}"
        if not partial:
            interval = self.model.NewOptionalIntervalVar(
                block.start_minute, block.minutes, block.end_minute, var, f"iv:{name}"
            )
            return Interval(block.start_minute, block.minutes, block.end_minute, interval, block)
        start = self.model.NewIntVar(block.start_minute, block.end_minute - 1, f"start:{name}")
        size = self.model.NewIntVar(1, block.minutes, f"size:{name}")
        end = self.model.NewIntVar(block.start_minute + 1, block.end_minute, f"end:{name}")
        interval = self.model.NewOptionalIntervalVar(start, size, end, var, f"iv:{name}")
        return Interval(start, size, end, interval, block)

    # -- lookup, with past dates as constants ---------------------------------------------

    def lookup(self, staff_id: str, activity_id: str, role: str | None, day: date, block: str):
        """The assignment literal, or a constant for a past or future date."""
        if day == self.dataset.target:
            return self.x.get(Slot(staff_id, activity_id, role, block), False)
        return (staff_id, activity_id, role, block) in self._past.get(day, {})

    def past_minutes(self, staff_id: str, activity_id: str, day: date, block: str) -> int:
        """Minutes a published ad hoc assignment took, or 0."""
        return self._past.get(day, {}).get((staff_id, activity_id, None, block), 0)

    def filled(self, activity_id: str, day: date, block: str) -> Literal:
        """Whether the activity runs fully staffed in this block on this date."""
        if day == self.dataset.target:
            instance = self.instances.get((activity_id, block))
            return False if instance is None else instance.filled
        past = self._past.get(day, {})
        positions = self.dataset.activities[activity_id].positions
        return all(any(key[1:] == (activity_id, p.role, block) for key in past) for p in positions)

    def holders_outside(self, activity_id: str, day: date, block: str, pool) -> list[Literal]:
        """Literals for position holders not in the pool (True constants for past dates)."""
        if day == self.dataset.target:
            instance = self.instances.get((activity_id, block))
            if instance is None:
                return []
            return [
                v
                for holders in instance.holders.values()
                for s, v in holders.items()
                if s not in pool
            ]
        return [
            True
            for key in self._past.get(day, {})
            if key[1] == activity_id and key[3] == block and key[0] not in pool
        ]

    def is_free(self, staff_id: str, day: date, block: str) -> Literal:
        """Free literal for the target date, or a constant for a past date."""
        if day == self.dataset.target:
            return self.free(staff_id, block)
        blocks = self.dataset.blocks
        return not any(
            key[0] == staff_id and blocks[key[3]].overlaps(blocks[block])
            for key in self._past.get(day, {})
        )

    def past_assignments(self, day: date):
        """Published (staff, activity, role, block) keys on a past date."""
        return self._past.get(day, {}).keys()

    # -- finish -----------------------------------------------------------------------------

    def finish(self) -> None:
        """Define every free literal in terms of the assignment variables. Call once."""
        blocks = self.dataset.blocks
        for (staff_id, block), free in self.free_literals.items():
            busy = {
                var.Index(): var
                for slot, var in self.x.items()
                if slot.staff == staff_id and blocks[slot.block].overlaps(blocks[block])
            }
            if not busy:
                self.model.Add(free == 1)
                continue
            self.model.AddBoolOr(list(busy.values())).OnlyEnforceIf(free.Not())
            self.model.AddBoolAnd([v.Not() for v in busy.values()]).OnlyEnforceIf(free)

    def unique_instances(self) -> list[Instance]:
        """Each instance once (a (DBL) instance is keyed by both of its blocks)."""
        seen: dict[int, Instance] = {}
        for instance in self.instances.values():
            seen.setdefault(id(instance), instance)
        return list(seen.values())
