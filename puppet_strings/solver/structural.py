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
        if not dataset.staff[slot.staff].available:
            model.Add(var == 0)  # not working today, whoever asked for them
    _no_double_booking(model, variables, dataset)


def _no_double_booking(model, variables: Variables, dataset: Dataset) -> None:
    """A person's assignments never overlap in time, within a block or across blocks."""
    by_staff: dict[str, list] = {}
    for slot, interval in variables.intervals.items():
        by_staff.setdefault(slot.staff, []).append(interval.interval)
    for intervals in by_staff.values():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
