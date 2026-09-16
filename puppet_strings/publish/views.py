"""The two printable views of a schedule, and the report, as tables."""

from puppet_strings.model import (
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    TRAINEE_ROLES,
    Assignment,
    Dataset,
)
from puppet_strings.sheets.source import Table
from puppet_strings.solver.result import Result

AVAILABLE = "Available"
PLAYSTATION = "playstation"
ANY_CLINIC = "any_clinic"


def staff_view(dataset: Dataset, assignments: tuple[Assignment, ...]) -> Table:
    """One row per staff member, one column per block (display groups merge)."""
    columns = _columns(dataset)
    header = ["Staff"] + [label for label, _ in columns]
    rows: Table = [header]
    by_staff_block: dict[tuple[str, str], list[str]] = {}
    for a in assignments:
        by_staff_block.setdefault((a.staff, a.block), []).append(_describe(dataset, a))
    for staff_id in sorted(dataset.staff, key=lambda s: dataset.staff[s].name):
        row = [dataset.staff[staff_id].name]
        for _, blocks in columns:
            cells = [c for b in blocks for c in by_staff_block.get((staff_id, b), [])]
            if not cells and PLAYSTATION in blocks:
                cells = [AVAILABLE]
            row.append("; ".join(cells))
        rows.append(row)
    return rows


def clinic_view(dataset: Dataset, assignments: tuple[Assignment, ...]) -> Table:
    """One row per clinic, one column per clinic block, staff in position order."""
    clinic_blocks = [
        b.id
        for b in dataset.blocks_on(dataset.target)
        if b.id in dataset.block_categories.get("any_clinic", ())
    ]
    rows: Table = [["Clinic"] + [_label(dataset, b) for b in clinic_blocks]]
    activities = sorted(
        {a.activity for a in assignments if a.activity in dataset.activities},
        key=lambda i: dataset.activities[i].name,
    )
    for activity_id in activities:
        row = [dataset.activities[activity_id].name]
        for block in clinic_blocks:
            here = [a for a in assignments if a.activity == activity_id and a.block == block]
            here.sort(key=lambda a: _role_order(a.role))
            row.append("\n".join(_holder(dataset, a) for a in here))
        rows.append(row)
    return rows


def report(result: Result) -> Table:
    """Unsatisfied requests, deferred requests, and conflicts."""
    rows: Table = [["status", "request", "priority", "description"]]
    for outcome in result.unsatisfied:
        rows.append(["unsatisfied", outcome.id, outcome.priority.value, outcome.description])
    for outcome in result.deferred:
        rows.append(["deferred", outcome.id, outcome.priority.value, outcome.description])
    for request_id in result.conflicts:
        rows.append(["conflict", request_id, "MUST_HAPPEN", "infeasible together"])
    for note in result.notes:
        rows.append(["note", "", "", note])
    return rows


def _columns(dataset: Dataset) -> list[tuple[str, list[str]]]:
    columns: list[tuple[str, list[str]]] = []
    seen_groups: dict[str, int] = {}
    for block in dataset.blocks_on(dataset.target):
        if block.display_group and block.display_group in seen_groups:
            columns[seen_groups[block.display_group]][1].append(block.id)
            continue
        if block.display_group:
            seen_groups[block.display_group] = len(columns)
        columns.append((_label(dataset, block.id), [block.id]))
    return columns


def _label(dataset: Dataset, block_id: str) -> str:
    block = dataset.blocks[block_id]
    return (block.display_group or block.id).replace("_", " ").title()


def _describe(dataset: Dataset, a: Assignment) -> str:
    if a.activity not in dataset.activities:
        return a.activity
    name = dataset.activities[a.activity].name
    if a.role in TRAINEE_ROLES or a.role in LIFEGUARD_ROLES:
        return f"{name} ({a.role})"
    if len(dataset.activities[a.activity].positions) > 1:
        return f"{name} ({_ordinal(a.role)})"
    return name


def _holder(dataset: Dataset, a: Assignment) -> str:
    name = dataset.staff[a.staff].name
    if a.role in TRAINEE_ROLES or a.role in LIFEGUARD_ROLES:
        return f"{name} ({a.role})"
    return name


def _role_order(role: str | None) -> int:
    ordered = POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES
    return ordered.index(role) if role in ordered else len(ordered)


def _ordinal(role: str | None) -> str:
    return {"first": "1st", "second": "2nd", "third": "3rd"}.get(role or "", role or "")
