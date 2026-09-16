"""The two printable views of a schedule, and the report, as tables."""

from dataclasses import dataclass

from puppet_strings.config import DEFAULT_REMAINDER
from puppet_strings.model import (
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    SCAFFOLDED,
    SHADOW,
    TRAINEE_ROLES,
    Assignment,
    Block,
    Dataset,
    minute_to_time,
)
from puppet_strings.sheets.source import Table
from puppet_strings.solver.result import Result

AVAILABLE = "Available"
FREE = "free"
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


@dataclass(frozen=True)
class Styled:
    """A table plus the formatting Google Sheets should apply to it."""

    rows: Table
    title_span: int = 0  # merge row 1 across this many columns
    bold_rows: tuple[int, ...] = ()  # 0-based row indexes
    freeze_rows: int = 0


TRAINEE_LABELS = {SHADOW: "Shadow", SCAFFOLDED: "Scaffold"}


def clinic_view(
    dataset: Dataset, assignments: tuple[Assignment, ...], remainder: str = DEFAULT_REMAINDER
) -> Styled:
    """The printed clinic schedule: one column per clinic block.

    Clinics come first, grouped by category in Clinic_Data order, one row per position
    holder (1st above 2nd) and a Shadow or Scaffold row for trainees. Offered clinics with
    nobody assigned keep their row. Then every other task, one name per row, and finally
    `remainder` listing staff with nothing in that block.
    """
    clinic_ids = dataset.block_categories.get(ANY_CLINIC, frozenset())
    blocks = [b.id for b in dataset.blocks_on(dataset.target) if b.id in clinic_ids]
    names = {s: dataset.staff[s].name for s in dataset.staff}
    rows: Table = [[_title(dataset)], ["Clinic"] + [_label(b) for b in blocks]]
    bold = [0, 1]
    by_activity_block: dict[tuple[str, str], list[Assignment]] = {}
    for a in assignments:
        if a.block in blocks:
            by_activity_block.setdefault((a.activity, a.block), []).append(a)

    shown = _offered(dataset) | {
        a.activity for a in assignments if a.activity in dataset.activities
    }
    for category in dict.fromkeys(a.category for a in dataset.activities.values()):
        activities = [
            a for a in dataset.activities.values() if a.category == category and a.id in shown
        ]
        if not activities:
            continue
        for activity in activities:
            bold.append(len(rows))
            holders = {
                b: [
                    names[a.staff]
                    for a in sorted(
                        _holders(by_activity_block.get((activity.id, b), [])),
                        key=lambda a: _role_order(a.role),
                    )
                ]
                for b in blocks
            }
            rows += _stack(activity.name, holders, blocks)
            for role, label in TRAINEE_LABELS.items():
                trainees = {
                    b: [
                        names[a.staff]
                        for a in by_activity_block.get((activity.id, b), [])
                        if a.role == role
                    ]
                    for b in blocks
                }
                if any(trainees.values()):
                    rows += _stack(label, trainees, blocks)
        rows.append([])

    tasks = dict.fromkeys(a.activity for a in assignments if a.activity not in dataset.activities)
    for task in tasks:
        bold.append(len(rows))
        people = {b: [names[a.staff] for a in by_activity_block.get((task, b), [])] for b in blocks}
        rows += _stack(task, people, blocks)
    if tasks:
        rows.append([])

    bold.append(len(rows))
    busy = {(a.staff, a.block) for a in assignments}
    free = {
        b: [names[s] for s in sorted(names, key=names.get) if (s, b) not in busy] for b in blocks
    }
    rows += _stack(remainder, free, blocks)
    return Styled(rows, title_span=len(blocks) + 1, bold_rows=tuple(bold), freeze_rows=2)


def _title(dataset: Dataset) -> str:
    day = dataset.session_dates.index(dataset.target) + 1
    session = dataset.calendar[dataset.target].session.replace("_", " ").title()
    return f"Day {day}, {session} - {dataset.target:%A}"


def _offered(dataset: Dataset) -> set[str]:
    prefix = f"offering:{dataset.target.isoformat()}:"
    return {
        r.id[len(prefix) :].rsplit(":", 1)[0] for r in dataset.requests if r.id.startswith(prefix)
    }


def _holders(here: list[Assignment]) -> list[Assignment]:
    return [a for a in here if a.role not in TRAINEE_ROLES]


def _stack(label: str, per_block: dict[str, list[str]], blocks: list[str]) -> Table:
    """Rows for one label: the label once, then one name per row in each block's column."""
    height = max([len(v) for v in per_block.values()] + [1])
    rows = []
    for i in range(height):
        cells = [label if i == 0 else ""]
        cells += [per_block[b][i] if i < len(per_block[b]) else "" for b in blocks]
        rows.append(cells)
    return rows


def changes_view(dataset: Dataset, result: Result) -> Table:
    """One row per staff member and block that a same-day re-solve moved."""
    rows: Table = [["Staff", "Block", "Was", "Now"]]
    for change in result.changes:
        rows.append(
            [
                dataset.staff[change.staff].name,
                _label(change.block),
                _held(dataset, change.before),
                _held(dataset, change.after),
            ]
        )
    return rows


def _held(dataset: Dataset, assignments: tuple[Assignment, ...]) -> str:
    return ", ".join(_timed(dataset, a) for a in assignments) or FREE


def _timed(dataset: Dataset, a: Assignment) -> str:
    """The task, with its times when it takes only part of its block."""
    text = _describe(dataset, a)
    if a.minutes >= dataset.blocks[a.block].minutes:
        return text
    return f"{text} {a.start:%H:%M}-{minute_to_time(a.end_minute):%H:%M}"


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


def _role_order(role: str | None) -> int:
    ordered = POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES
    return ordered.index(role) if role in ordered else len(ordered)


def _ordinal(role: str | None) -> str:
    return {"first": "1st", "second": "2nd", "third": "3rd"}.get(role or "", role or "")
