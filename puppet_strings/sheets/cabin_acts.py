"""The Board tab of a cabin act sheet: what each cabin is doing in the cabin act block.

Someone else fills these in, one spreadsheet per session and week, and the title says
which: "Cabin Act Sorting - S5W1" is session 5, week 1. The Board is a grid of cabins down
the side and weekdays across the top, each weekday four columns wide:

    row 1  the sheet's title
    row 2  a weekday merged over its four columns, then spare "Extra" columns
    row 4+ one block of rows per cabin, the cabin merged down column A

Inside a cabin's block each weekday holds a label column and a value column beside it, so
`Activity`, `Location` and `HEROES` are read by their labels rather than by counting rows.
Merged cells carry their value in the top-left cell only, which is why a cabin name or a
weekday appears once and holds until the next one.

Only the labels this module names are read; everything else on the grid is for the people
filling it in. The Support Requests tab says the same thing a second time and is ignored.
"""

import re
from dataclasses import dataclass

from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, split_list

TITLE_ROW = 0
DAY_ROW = 1
FIRST_CABIN_ROW = 3
CABIN_COLUMN = 0

ACTIVITY = "activity"
HEROES = "heroes"

# Cabin acts are scheduled Monday to Friday; the grid's spare "Extra" columns head no day.
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")

# "Cabin Act Sorting - S5W1" -> session 5, week 1.
TITLE_PATTERN = re.compile(r"s\s*(\d+)\s*w\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class CabinAct:
    """One cabin's activity in the cabin act block on one weekday.

    `heroes` is the HEROES cell split on commas, each item naming a staff member, a staff
    category or a skill. `weekday` is lowercase; the date it falls on comes from the
    Calendar sheet and the session and week in the sheet's title.
    """

    cabin: str
    weekday: str
    activity: str
    heroes: tuple[str, ...]


def parse_title(title: str, where: str) -> tuple[int, int]:
    """The session and week a cabin act sheet is for, read off its title."""
    match = TITLE_PATTERN.search(title)
    if not match:
        raise LoadError(
            f"{where}: the title says no session and week; name the sheet like "
            "'Cabin Act Sorting - S5W1'"
        )
    return int(match.group(1)), int(match.group(2))


def parse_board(table: Table, where: str) -> tuple[CabinAct, ...]:
    """Every cabin act on a Board tab, in cabin then weekday order.

    A cabin with nothing written against a weekday yields nothing, so a mostly empty sheet
    costs nothing to read.
    """
    if len(table) <= FIRST_CABIN_ROW:
        raise LoadError(f"{where}: expected a weekday row and a row of cabins below it")
    days = _weekday_columns(table[DAY_ROW], where)
    acts = []
    cabin = ""
    fields: dict[tuple[str, str], dict[str, str]] = {}
    for cells in table[FIRST_CABIN_ROW:]:
        name = _cell(cells, CABIN_COLUMN)
        cabin = name or cabin  # the cabin is merged down its block, so it holds
        if not cabin:
            continue
        for column, weekday in days:
            label = normalize(_cell(cells, column))
            if label in (ACTIVITY, HEROES):
                fields.setdefault((cabin, weekday), {})[label] = _cell(cells, column + 1)
    for (name, weekday), written in fields.items():
        heroes = tuple(split_list(written.get(HEROES, "")))
        if heroes:  # an act nobody is asked for needs no request
            acts.append(CabinAct(name, weekday, written.get(ACTIVITY, ""), heroes))
    return tuple(acts)


def _weekday_columns(header: list[str], where: str) -> list[tuple[int, str]]:
    """The left-hand column of each Monday-to-Friday group, with the day it heads."""
    columns = [
        (column, normalize(cell))
        for column, cell in enumerate(header)
        if normalize(cell) in WEEKDAYS
    ]
    if not columns:
        raise LoadError(
            f"{where}: row {DAY_ROW + 1} heads no weekday; it should read Monday, Tuesday, …"
        )
    return columns


def _cell(cells: list[str], column: int) -> str:
    return cells[column].strip() if column < len(cells) else ""
