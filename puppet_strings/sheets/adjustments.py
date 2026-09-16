"""Adjustments: one-day changes to a staff member's RAL.

One row per staff member per date. A row for the target date replaces that person's RAL
from the Skills sheet for that day only, which is how a short night becomes a lower RAL
without touching anyone's permanent record.
"""

from collections.abc import Mapping
from datetime import date

from puppet_strings.model import MAX_RAL, Adjustment, Staff
from puppet_strings.sheets.calendar import parse_date
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

COLUMNS = ("date", "staff", "ral", "note")


def parse_adjustments(table: Table, staff: Mapping[str, Staff]) -> tuple[Adjustment, ...]:
    """Every adjustment on the sheet, in sheet order."""
    where = "Adjustments"
    rows = header_rows(table, ("date", "staff", "ral"), where)
    by_name = {member.name: member.id for member in staff.values()}
    adjustments = []
    for row in rows:
        cell = f"{where} row '{row['date']} {row['staff']}'"
        if row["staff"] not in by_name:
            raise LoadError(f"{cell}: '{row['staff']}' is not on the Skills sheet")
        ral = parse_int(row["ral"], cell)
        if not 1 <= ral <= MAX_RAL:
            raise LoadError(f"{cell}: RAL {ral} must be between 1 and {MAX_RAL}")
        adjustments.append(
            Adjustment(
                date=parse_date(row["date"], cell),
                staff=by_name[row["staff"]],
                ral=ral,
                note=row.get("note", ""),
            )
        )
    return tuple(adjustments)


def adjustment_rows(adjustments: tuple[Adjustment, ...], staff: Mapping[str, Staff]) -> Table:
    """Adjustments as a table with a header row, for writing."""
    rows: Table = [list(COLUMNS)]
    for a in sorted(adjustments, key=lambda a: (a.date, staff[a.staff].name)):
        rows.append([a.date.isoformat(), staff[a.staff].name, str(a.ral), a.note])
    return rows


def on_date(adjustments: tuple[Adjustment, ...], day: date) -> tuple[Adjustment, ...]:
    """The adjustments that apply on one date, one per staff member (the last row wins)."""
    latest = {a.staff: a for a in adjustments if a.date == day}
    return tuple(latest.values())
