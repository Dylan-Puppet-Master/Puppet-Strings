"""Published Schedules: one tab per date, one row per assignment.

`start` (HH:MM) and `minutes` place the assignment inside its block. A clinic fills its
block; an ad hoc task scheduled with `FOR` may fill part of it.
"""

from collections.abc import Mapping
from datetime import date

from puppet_strings.model import Activity, Assignment, Staff
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int, parse_time

COLUMNS = ("staff", "activity", "role", "block", "start", "minutes", "source")


def parse_published(
    table: Table,
    day: date,
    staff: Mapping[str, Staff],
    activities: Mapping[str, Activity],
) -> tuple[Assignment, ...]:
    """Assignments on one published date. Ad hoc activities are written in quotes."""
    where = f"Published Schedules/{day.isoformat()}"
    rows = header_rows(table, COLUMNS, where)
    staff_ids = {s.name: s.id for s in staff.values()}
    activity_ids = {a.name: a.id for a in activities.values()}
    assignments = []
    for row in rows:
        cell = f"{where} row {row['staff']} / {row['activity']}"
        if row["staff"] not in staff_ids:
            raise LoadError(f"{cell}: unknown staff member")
        text = row["activity"]
        if text.startswith("'") and text.endswith("'"):
            activity = text[1:-1]
        elif text in activity_ids:
            activity = activity_ids[text]
        else:
            raise LoadError(f"{cell}: unknown activity")
        assignments.append(
            Assignment(
                staff=staff_ids[row["staff"]],
                activity=activity,
                role=row["role"] or None,
                date=day,
                block=row["block"],
                start=parse_time(row["start"], cell),
                minutes=parse_int(row["minutes"], cell),
                source=row["source"],
            )
        )
    return tuple(assignments)


def assignment_rows(
    assignments: tuple[Assignment, ...],
    staff: Mapping[str, Staff],
    activities: Mapping[str, Activity],
) -> Table:
    """Assignments as a table with a header row, for writing."""
    rows: Table = [list(COLUMNS)]
    order = lambda a: (a.block, a.start, a.activity, a.role or "", a.staff)  # noqa: E731
    for a in sorted(assignments, key=order):
        activity = activities[a.activity].name if a.activity in activities else f"'{a.activity}'"
        start = a.start.strftime("%H:%M")
        rows.append(
            [staff[a.staff].name, activity, a.role or "", a.block, start, str(a.minutes), a.source]
        )
    return rows
