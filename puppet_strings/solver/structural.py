"""Constraints that hold on every run, generated from sheet data rather than requests."""

from ortools.sat.python import cp_model

from puppet_strings.model import SHADOW, Dataset
from puppet_strings.solver.variables import LIFEGUARD, Variables


def add_structural_constraints(model: cp_model.CpModel, variables: Variables, dataset: Dataset):
    """Positions, lifeguards, trainees, and no double booking."""
    for instance in variables.unique_instances():
        activity = instance.activity
        for holders in instance.holders.values():
            model.Add(sum(holders.values()) == instance.filled)
        if activity.lifeguards:
            lifeguards = [
                var
                for holders in instance.holders.values()
                for staff_id, var in holders.items()
                if dataset.staff[staff_id].status(LIFEGUARD).eligible
            ]
            model.Add(sum(lifeguards) >= activity.lifeguards * instance.filled)
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
    _no_double_booking(model, variables, dataset)


def _no_double_booking(model, variables: Variables, dataset: Dataset) -> None:
    by_staff_block: dict[tuple[str, str], dict[int, cp_model.IntVar]] = {}
    for slot, var in variables.x.items():
        by_staff_block.setdefault((slot.staff, slot.block), {})[var.Index()] = var
    blocks = list(dataset.blocks.values())
    overlapping = [
        (a.id, b.id) for i, a in enumerate(blocks) for b in blocks[i + 1 :] if a.overlaps(b)
    ]
    for vars_here in by_staff_block.values():
        model.AddAtMostOne(vars_here.values())
    for staff_id in dataset.staff:
        for first, second in overlapping:
            merged = {
                **by_staff_block.get((staff_id, first), {}),
                **by_staff_block.get((staff_id, second), {}),
            }
            if len(merged) > 1:
                model.AddAtMostOne(merged.values())
