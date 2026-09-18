"""Constraints that hold on every run, generated from sheet data rather than requests."""

from ortools.sat.python import cp_model

from puppet_strings.model import SHADOW, Dataset
from puppet_strings.solver.variables import Variables


def add_structural_constraints(model: cp_model.CpModel, variables: Variables, dataset: Dataset):
    """Positions (including lifeguard positions), trainees, and no overlapping assignments."""
    for instance in variables.unique_instances():
        activity = instance.activity
        for holders in instance.holders.values():
            model.Add(sum(holders.values()) == instance.filled)
        for role, var in instance.trainees.values():
            if role == SHADOW:
                model.AddImplication(var, instance.filled)
                continue
            supervisors = [
                instance.holders[position.role][holder]
                for position in activity.positions
                for holder in instance.holders.get(position.role, {})
                if dataset.staff[holder].status(position.skill).can_scaffold
            ]
            model.AddBoolOr(supervisors).OnlyEnforceIf(var)
        if instance.trainees:
            model.AddAtMostOne(var for _, var in instance.trainees.values())
    for slot, var in variables.x.items():
        if slot.block in dataset.staff[slot.staff].resting_blocks:
            model.Add(var == 0)  # resting then, whoever asked for them
    _no_double_booking(model, variables, dataset)


def _no_double_booking(model, variables: Variables, dataset: Dataset) -> None:
    """A person's assignments never overlap in time, within a block or across blocks.

    Assignments in blocks that never overlap cannot clash, so each person gets one
    constraint per group of blocks that all overlap each other: at most one assignment when
    every one fills its block, and a no-overlap over the intervals when a task can move
    within it.

    A group is the blocks running at one instant, taken at each block's start. Blocks
    running at the same instant do all overlap, and two blocks that overlap are both
    running at the later one's start, so every clashing pair lands in a group. Grouping
    instead by "the blocks overlapping this one" would be wrong: overlap is not
    transitive, so a midday block that overlaps two clinics would put those two clinics in
    one at-most-one group and stop anyone from working both.
    """
    blocks = dataset.blocks_on(dataset.target)  # a block on another kind of day cannot clash
    groups = {
        frozenset(c.id for c in blocks if c.start_minute <= instant < c.end_minute)
        for instant in {b.start_minute for b in blocks}
    }
    for slots in variables.by_staff.values():
        for group in groups:
            here = [slot for slot in slots if slot.block in group]
            if len(here) < 2:
                continue
            intervals = [variables.intervals[slot] for slot in here]
            if any(interval.partial for interval in intervals):
                model.AddNoOverlap([interval.interval for interval in intervals])
            else:
                model.AddAtMostOne(
                    {variables.x[slot].Index(): variables.x[slot] for slot in here}.values()
                )
