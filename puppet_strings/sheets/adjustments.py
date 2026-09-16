"""Adjustments: one-day changes to a staff member's RAL.

One row per staff member per date, applying to that day only and leaving the Skills sheet
alone. `available` set to no takes someone off the day; `ral` lowers their risk assessment
level for it. A row must do one or the other.
"""

from collections.abc import Mapping
from datetime import date

from puppet_strings.model import MAX_RAL, Adjustment, Staff
from puppet_strings.sheets.calendar import parse_date
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

COLUMNS = ("date", "staff", "available", "ral", "note")
NO = ("no", "n", "false", "0")


def parse_adjustments(table: Table, staff: Mapping[str, Staff]) -> tuple[Adjustment, ...]:
    """Every adjustment on the sheet, in sheet order."""
    where = "Adjustments"
    rows = header_rows(table, ("date", "staff"), where)
    by_name = {member.name: member.id for member in staff.values()}
    adjustments = []
    for row in rows:
        cell = f"{where} row '{row['date']} {row['staff']}'"
        if row["staff"] not in by_name:
            raise LoadError(f"{cell}: '{row['staff']}' is not on the Skills sheet")
        available = row.get("available", "").strip().lower() not in NO
        ral = parse_int(row["ral"], cell) if row.get("ral") else None
        if ral is not None and not 1 <= ral <= MAX_RAL:
            raise LoadError(f"{cell}: RAL {ral} must be between 1 and {MAX_RAL}")
        if available and ral is None:
            raise LoadError(f"{cell}: set `available` to no, or give a `ral`, or delete the row")
        adjustments.append(
            Adjustment(
                date=parse_date(row["date"], cell),
                staff=by_name[row["staff"]],
                available=available,
                ral=ral,
                note=row.get("note", ""),
            )
        )
    return tuple(adjustments)


def adjustment_rows(adjustments: tuple[Adjustment, ...], staff: Mapping[str, Staff]) -> Table:
    """Adjustments as a table with a header row, for writing."""
    rows: Table = [list(COLUMNS)]
    for a in sorted(adjustments, key=lambda a: (a.date, staff[a.staff].name)):
        available = "" if a.available else "no"
        ral = "" if a.ral is None else str(a.ral)
        rows.append([a.date.isoformat(), staff[a.staff].name, available, ral, a.note])
    return rows


def on_date(adjustments: tuple[Adjustment, ...], day: date) -> tuple[Adjustment, ...]:
    """The adjustments that apply on one date, one per staff member (the last row wins)."""
    return tuple({a.staff: a for a in adjustments if a.date == day}.values())
