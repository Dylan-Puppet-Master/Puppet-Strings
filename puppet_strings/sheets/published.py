"""Published Schedules: one tab per date, one row per assignment."""

from collections.abc import Mapping
from datetime import date

from puppet_strings.model import Activity, Assignment, Staff
from puppet_strings.sheets.source import LoadError, Table, header_rows

COLUMNS = ("staff", "activity", "role", "block", "source")


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
    for a in sorted(assignments, key=lambda a: (a.block, a.activity, a.role or "", a.staff)):
        activity = activities[a.activity].name if a.activity in activities else f"'{a.activity}'"
        rows.append([staff[a.staff].name, activity, a.role or "", a.block, a.source])
    return rows
