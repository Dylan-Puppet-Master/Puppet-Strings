"""The two printable views of a schedule, and the report, as tables."""

from puppet_strings.config import DEFAULT_REMAINDER
from puppet_strings.model import (
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    TRAINEE_ROLES,
    Assignment,
    Block,
    Dataset,
)
from puppet_strings.sheets.source import Table
from puppet_strings.solver.result import Result

AVAILABLE = "Available"
PLAYSTATION = "playstation"
ANY_CLINIC = "any_clinic"


def staff_view(
    dataset: Dataset, assignments: tuple[Assignment, ...], remainder: str = DEFAULT_REMAINDER
) -> Table:
    """One row per staff member, one column per block.

    A block's cell lists the person's tasks in time order, joined by ", then ". Time in the
    block that no task covers is labeled with `remainder` (DYOW/WPs by default).
    """
    blocks = dataset.blocks_on(dataset.target)
    rows: Table = [["Staff"] + [_label(b.id) for b in blocks]]
    by_staff_block: dict[tuple[str, str], list[Assignment]] = {}
    for a in assignments:
        by_staff_block.setdefault((a.staff, a.block), []).append(a)
    for staff_id in sorted(dataset.staff, key=lambda s: dataset.staff[s].name):
        row = [dataset.staff[staff_id].name]
        for block in blocks:
            here = sorted(by_staff_block.get((staff_id, block.id), []), key=lambda a: a.start)
            row.append(_cell(dataset, block, here, remainder))
        rows.append(row)
    return rows


def _cell(dataset: Dataset, block: Block, here: list[Assignment], remainder: str) -> str:
    if not here:
        return AVAILABLE if block.id == PLAYSTATION else ""
    segments = []
    cursor = block.start_minute
    for a in here:
        if _minute(a.start) > cursor:
            segments.append(remainder)
        segments.append(_describe(dataset, a))
        cursor = a.end_minute
    if cursor < block.end_minute:
        segments.append(remainder)
    return ", then ".join(segments)


def _minute(t) -> int:
    return t.hour * 60 + t.minute


def clinic_view(dataset: Dataset, assignments: tuple[Assignment, ...]) -> Table:
    """One row per clinic, one column per clinic block, staff in position order."""
    clinic_blocks = [
        b.id
        for b in dataset.blocks_on(dataset.target)
        if b.id in dataset.block_categories.get("any_clinic", ())
    ]
    rows: Table = [["Clinic"] + [_label(b) for b in clinic_blocks]]
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


def _label(block_id: str) -> str:
    return block_id.replace("_", " ").title()


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
