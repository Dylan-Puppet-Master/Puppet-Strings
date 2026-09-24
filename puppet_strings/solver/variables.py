"""Assignment variables: one boolean per (staff, activity, role, block) on the target date.

Every variable carries a time interval inside its block. A clinic position fills the block;
a quoted task has a movable start and a variable length, so `FOR 30m` can take part of a
block. Past dates come from Published Schedules and are looked up as plain values.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from puppet_strings.model import Activity, Assignment, Block, Dataset

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
        self.by_staff: dict[str, list[Slot]] = {}  # every slot, by staff member
        self.slots: dict[tuple[str, str], list[Slot]] = {}  # every slot, by staff and activity

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
                if member.resting_blocks.intersection(blocks) or not position.allows(member):
                    continue
                var = self.model.NewBoolVar(f"x:{member.id}:{activity_id}:{position.role}")
                holders[member.id] = var
                self._register(member.id, activity_id, position.role, blocks, var, source)
        for block in blocks:
            self.instances[activity_id, block] = instance
        return instance

    def trainee(self, staff_id: str, activity_id: str, block: str, source: str) -> tuple:
        """(role, variable) for a staff member training on an instance; (None, False) if none."""
        instance = self.instances.get((activity_id, block))
        if instance is None or block in self.dataset.staff[staff_id].resting_blocks:
            return None, False
        if staff_id in instance.trainees:
            return instance.trainees[staff_id]
        skill = instance.activity.positions[0].skill if instance.activity.positions else None
        role = self.dataset.staff[staff_id].status(skill).trainee_role
        var = self.model.NewBoolVar(f"x:{staff_id}:{activity_id}:{role}")
        instance.trainees[staff_id] = (role, var)
        self._register(staff_id, activity_id, role, instance.blocks, var, source)
        return role, var

    def adhoc(self, staff_id: str, text: str, block: str, source: str) -> cp_model.IntVar:
        """The variable for a staff member doing a quoted task in a block."""
        slot = Slot(staff_id, text, None, block)
        if slot not in self.x:
            var = self.model.NewBoolVar(f"x:{staff_id}:{text}:{block}")
            self._register(staff_id, text, None, (block,), var, source, partial=True)
        return self.x[slot]

    def free(self, staff_id: str, block: str) -> Literal:
        """True iff the person has nothing overlapping this block; False when resting through it."""
        if block in self.dataset.staff[staff_id].resting_blocks:
            return False
        key = (staff_id, block)
        if key not in self.free_literals:
            self.free_literals[key] = self.model.NewBoolVar(f"free:{staff_id}:{block}")
        return self.free_literals[key]

    def busy(self, staff_id: str, block: str) -> Literal:
        """True iff the person holds something overlapping this block; False when resting."""
        free = self.free(staff_id, block)
        return False if free is False else free.Not()

    def _register(self, staff_id, activity_id, role, blocks, var, source, partial=False):
        for block in blocks:
            slot = Slot(staff_id, activity_id, role, block)
            self.x[slot] = var
            self.sources[slot] = source
            self.intervals[slot] = self._interval(slot, var, partial)
            self.by_staff.setdefault(staff_id, []).append(slot)
            self.slots.setdefault((staff_id, activity_id), []).append(slot)

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

    # -- lookup on the target date --------------------------------------------------------

    def lookup(self, staff_id: str, activity_id: str, role: str | None, block: str) -> Literal:
        """The assignment variable, or False if nothing can put them there."""
        return self.x.get(Slot(staff_id, activity_id, role, block), False)

    def holders(self, staff_id: str, activity_id: str, block: str) -> list[cp_model.IntVar]:
        """The variables for a staff member holding any position of an activity in a block."""
        instance = self.instances.get((activity_id, block))
        if instance is None:
            return []
        return [
            v for holders in instance.holders.values() for s, v in holders.items() if s == staff_id
        ]

    def members(
        self, staff_id: str, activity_id: str, block: str, roles: frozenset[str] | None = None
    ) -> list[cp_model.IntVar]:
        """The variables for a staff member being on an instance, in `roles` or (None) any.

        A trainee is on it too, in the trainee role they are.
        """
        if activity_id not in self.dataset.activities:
            var = self.lookup(staff_id, activity_id, None, block)
            return [] if var is False else [var]
        instance = self.instances.get((activity_id, block))
        if instance is None:
            return []
        found = [
            v
            for role, holders in instance.holders.items()
            if roles is None or role in roles
            for s, v in holders.items()
            if s == staff_id
        ]
        if staff_id in instance.trainees:
            role, var = instance.trainees[staff_id]
            if roles is None or role in roles:
                found.append(var)
        return found

    # -- published dates, as facts ---------------------------------------------------------

    def published(self, day: date) -> tuple[Assignment, ...]:
        """What was published for a past date."""
        return self.dataset.published.get(day, ())

    def was_free(self, staff_id: str, day: date, block: str) -> bool:
        """Whether nothing published overlaps this block for the person on a past date."""
        blocks = self.dataset.blocks
        return not any(
            a.staff == staff_id and blocks[a.block].overlaps(blocks[block])
            for a in self.published(day)
        )

    def was_member(
        self, staff_id: str, activity_id: str, day: date, block: str
    ) -> Iterator[Assignment]:
        """The published assignments putting a person on an instance on a past date."""
        for a in self.published(day):
            if a.staff == staff_id and a.activity == activity_id and a.block == block:
                yield a

    # -- finish -----------------------------------------------------------------------------

    def finish(self) -> None:
        """Define every free literal in terms of the assignment variables. Call once."""
        blocks = self.dataset.blocks
        for (staff_id, block), free in self.free_literals.items():
            busy = {
                self.x[slot].Index(): self.x[slot]
                for slot in self.by_staff.get(staff_id, ())
                if blocks[slot.block].overlaps(blocks[block])
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
