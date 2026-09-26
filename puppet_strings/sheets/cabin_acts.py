"""The Board tab of a cabin act sheet: what each cabin is doing in the cabin act block.

Someone else fills these in, one spreadsheet per session and week, and the title says
which: "Cabin Act Sorting - S5W1" is session 5, week 1. The Board is a grid of cabins down
the side and weekdays across the top, each weekday four columns wide:

    row 1  the sheet's title
    row 2  a weekday merged over its four columns, then spare "Extra" columns
    row 4+ one block of rows per cabin, the cabin merged down column A

Inside a cabin's block each weekday holds two label columns, each with its value beside it,
so `Activity`, `Location` and `HEROES` are read by their labels rather than by counting rows.
Merged cells carry their value in the top-left cell only, which is why a cabin name or a
weekday appears once and holds until the next one.

Only the labels this module names are read; everything else on the grid is for the people
filling it in. The Support Requests tab says the same thing a second time and is ignored.

Each act becomes an `Activity` under `activities.cabin_acts`, staffed like a clinic: one
position per hero the HEROES cell names. That is why a cabin act needs no requests of its
own — one request asks for all of them, and the positions say who by.

An act whose title starts or ends with "RH" or "Rest Hour" is moved to rest hour, and the
cabin rests in the cabin act block instead. It is marked so, and `activities.cabin_acts`
names the two kinds apart, `at_cabin_act.p4` and `at_rest_hour.p2`; which block each runs
in is still for a request to say.

A checkbox on the card, a label with TRUE or FALSE beside it, names the acts it is ticked
on: "Lvl 2 on Ground" makes `activities.cabin_acts.lvl_2_on_ground`.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from puppet_strings.model import POSITION_ROLES, Activity, Position, Staff
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, split_list

TITLE_ROW = 0
DAY_ROW = 1
FIRST_CABIN_ROW = 3
CABIN_COLUMN = 0

ACTIVITY = "activity"
HEROES = "heroes"

CABIN_ACT_CATEGORY = "cabin_act"
CABIN_ACT_BLOCK = "cabin_act"  # the Blocks sheet's own name for the slot they run in
MIN_RAL = 1  # a cabin act asks for people by name or skill, never by risk level
LABEL_PAIRS = 2  # a weekday is four columns: two labels, each with its value beside it

# Cabin acts are scheduled Monday to Friday; the grid's spare "Extra" columns head no day.
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")

# "Cabin Act Sorting - S5W1" -> session 5, week 1.
TITLE_PATTERN = re.compile(r"s\s*(\d+)\s*w\s*(\d+)", re.IGNORECASE)

# An act moved to rest hour says so at one end of its title, however the board spells it:
# "RH: Fruit Ninja", "RH - Bubble Lake", "REST HOUR Aerial Yoga", "Stranded - Rest Hour".
_REST_HOUR = r"(?:rh|rest\s*hour)"
AT_REST_HOUR = re.compile(rf"^\W*{_REST_HOUR}\b|\b{_REST_HOUR}\W*$", re.IGNORECASE)
MENTIONS_REST_HOUR = re.compile(rf"\b{_REST_HOUR}\b", re.IGNORECASE)


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
    card: tuple[tuple[str, str], ...] = ()  # every label on the card and what it says


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
    cards: dict[tuple[str, str], dict[str, str]] = {}
    for cells in table[FIRST_CABIN_ROW:]:
        name = _cell(cells, CABIN_COLUMN)
        cabin = name or cabin  # the cabin is merged down its block, so it holds
        if not cabin:
            continue
        for column, weekday in days:
            for pair in range(0, LABEL_PAIRS * 2, 2):
                label = _cell(cells, column + pair)
                if label:
                    cards.setdefault((cabin, weekday), {})[label] = _cell(cells, column + pair + 1)
    for (name, weekday), card in cards.items():
        written = {normalize(label): value for label, value in card.items()}
        heroes = tuple(split_list(written.get(HEROES, "")))
        if heroes:  # an act nobody is asked for needs nobody scheduled
            acts.append(
                CabinAct(
                    name,
                    weekday,
                    written.get(ACTIVITY, ""),
                    heroes,
                    tuple((label, value) for label, value in card.items() if value),
                )
            )
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


def cabin_act_activities(
    boards: Mapping[str, tuple[CabinAct, ...]],
    weeks: Mapping[tuple[int, int], Mapping[str, date]],
    staff: Mapping[str, Staff],
    categories: Mapping[str, frozenset[str]],
    skills: Mapping[str, str],
) -> tuple[dict[str, Activity], list[str]]:
    """Every cabin act on every sheet as an activity, plus warnings.

    `weeks` maps (session, week) to that week's dates by weekday name, read off the Calendar
    sheet. Anything that cannot be placed or named is a warning rather than an error: a
    typo in one cabin's HEROES cell should not cost the other hundred acts their staff.
    """
    activities: dict[str, Activity] = {}
    warnings: list[str] = []
    for title in sorted(boards):
        session, week = parse_title(title, title)
        days = weeks.get((session, week))
        if days is None:
            warnings.append(f"{title}: the Calendar sheet has no session {session} week {week}")
            continue
        for act in boards[title]:
            day = days.get(act.weekday)
            if day is None:
                warnings.append(
                    f"{title}: {act.cabin} is on a {act.weekday} that week has no day for"
                )
                continue
            activity, act_warnings = _activity(act, day, title, staff, categories, skills)
            warnings += act_warnings
            if activity is None:
                continue
            if activity.id in activities:
                warnings.append(f"{title}: {act.cabin} on {day} is on another sheet too")
                continue
            activities[activity.id] = activity
    return activities, warnings


def _activity(
    act: CabinAct,
    day: date,
    title: str,
    staff: Mapping[str, Staff],
    categories: Mapping[str, frozenset[str]],
    skills: Mapping[str, str],
) -> tuple[Activity | None, list[str]]:
    """One cabin act as an activity, with a position per hero its HEROES cell names."""
    positions, warnings = [], []
    for hero in act.heroes:
        # The check is before the hero rather than after the one before it: a board naming
        # exactly as many heroes as there are positions fills them and drops nothing, and
        # saying it asked for too many is a warning about a board that is perfectly fine.
        if len(positions) == len(POSITION_ROLES):
            warnings.append(f"{title}: {act.cabin} on {day} asks for more heroes than positions")
            break
        position = _position(hero, POSITION_ROLES[len(positions)], staff, categories, skills)
        if position is None:
            warnings.append(
                f"{title}: {act.cabin} on {day} asks for '{hero}', who is no staff member, "
                "staff category or skill"
            )
            continue
        positions.append(position)
    if not positions:  # an act nobody is asked for needs nobody scheduled
        return None, warnings
    rest_hour = bool(AT_REST_HOUR.search(act.activity))
    if not rest_hour and MENTIONS_REST_HOUR.search(act.activity):
        # "CA: Blackberry picking, RH: muffins" is split between the two blocks, and which
        # heroes are for which half is not something the board says
        warnings.append(
            f"{title}: {act.cabin} on {day} mentions rest hour in the middle of "
            f"'{act.activity}', so it is read as a cabin act block act"
        )
    return (
        Activity(
            name=f"{act.cabin} {act.activity}".strip() if act.activity else f"{act.cabin} CA",
            id=normalize(f"cabin act {act.cabin} {day}"),
            category=CABIN_ACT_CATEGORY,
            slots=0,
            positions=tuple(positions),
            cabin=act.cabin,
            day=day,
            card=act.card,
            rest_hour=rest_hour,
        ),
        warnings,
    )


def _position(
    hero: str,
    role: str,
    staff: Mapping[str, Staff],
    categories: Mapping[str, frozenset[str]],
    skills: Mapping[str, str],
) -> Position | None:
    """What one HEROES entry asks for: a person, anyone in a category, or anyone with a skill."""
    name = normalize(hero)
    if name in staff:
        return Position(role, None, MIN_RAL, frozenset({name}), hero)
    if name in categories:
        return Position(role, None, MIN_RAL, frozenset(categories[name]), hero)
    if name in skills:
        return Position(role, name, MIN_RAL, None, hero)
    return None
