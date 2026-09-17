"""Adjustments: one-day changes to what a staff member may do.

One row per staff member per date, applying to that day only and leaving the Skills sheet
alone. `resting` takes them off the whole day or half of it; `RAL_penalty` comes off their
usual RAL for the day. A row must do one or the other.
"""

from collections.abc import Mapping
from datetime import date

from puppet_strings.model import MAX_RAL, Adjustment, Rest, Staff
from puppet_strings.sheets.calendar import parse_date
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

COLUMNS = ("date", "staff", "resting", "RAL_penalty", "note")

# What the `resting` cell may say. Edit here to accept more wordings.
RESTING_WORDS = {
    "": Rest.NONE,
    "all day": Rest.ALL_DAY,
    "all": Rest.ALL_DAY,
    "full day": Rest.ALL_DAY,
    "morning": Rest.MORNING,
    "am": Rest.MORNING,
    "afternoon": Rest.AFTERNOON,
    "pm": Rest.AFTERNOON,
}


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
        resting = RESTING_WORDS.get(row.get("resting", "").strip().lower())
        if resting is None:
            allowed = ", ".join(sorted(w for w in RESTING_WORDS if w))
            raise LoadError(f"{cell}: resting '{row['resting']}' must be one of {allowed}")
        penalty = parse_int(row["RAL_penalty"], cell) if row.get("RAL_penalty") else 0
        if not 0 <= penalty <= MAX_RAL:
            raise LoadError(f"{cell}: RAL_penalty {penalty} must be between 1 and {MAX_RAL}")
        if resting is Rest.NONE and not penalty:
            raise LoadError(f"{cell}: give a `resting` or a `RAL_penalty`, or delete the row")
        adjustments.append(
            Adjustment(
                date=parse_date(row["date"], cell),
                staff=by_name[row["staff"]],
                resting=resting,
                ral_penalty=penalty,
                note=row.get("note", ""),
            )
        )
    return tuple(adjustments)


def adjustment_rows(adjustments: tuple[Adjustment, ...], staff: Mapping[str, Staff]) -> Table:
    """Adjustments as a table with a header row, for writing."""
    rows: Table = [list(COLUMNS)]
    for a in sorted(adjustments, key=lambda a: (a.date, staff[a.staff].name)):
        penalty = str(a.ral_penalty) if a.ral_penalty else ""
        rows.append([a.date.isoformat(), staff[a.staff].name, a.resting.value, penalty, a.note])
    return rows


def on_date(adjustments: tuple[Adjustment, ...], day: date) -> tuple[Adjustment, ...]:
    """The adjustments that apply on one date, one per staff member (the last row wins)."""
    return tuple({a.staff: a for a in adjustments if a.date == day}.values())


def resting_blocks(adjustment: Adjustment, blocks, midday) -> frozenset[str]:
    """The blocks a rest covers. A block belongs to the half of the day it starts in."""
    if adjustment.resting is Rest.NONE:
        return frozenset()
    if adjustment.resting is Rest.ALL_DAY:
        return frozenset(block.id for block in blocks)
    morning = adjustment.resting is Rest.MORNING
    return frozenset(block.id for block in blocks if (block.start < midday) == morning)
