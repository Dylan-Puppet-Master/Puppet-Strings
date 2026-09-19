"""Assemble a Dataset for one target date from every sheet."""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Dataset, Span, block_runs_on
from puppet_strings.names import normalize
from puppet_strings.sheets import metrics as metrics_sheet
from puppet_strings.sheets.adjustments import parse_adjustments, resting_blocks
from puppet_strings.sheets.blocks import ALL_BLOCKS, block_categories, parse_blocks
from puppet_strings.sheets.cabin_acts import cabin_act_activities, parse_board
from puppet_strings.sheets.calendar import calendar_days, parse_calendar, parse_date
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
from puppet_strings.sheets.requests import parse_requests
from puppet_strings.sheets.skills import (
    known_skills,
    parse_position_skills,
    parse_skills,
    trainers,
)
from puppet_strings.sheets.source import LoadError, Source

ADJUSTMENT_HEADER = ("date", "staff", "resting", "RAL_penalty", "note")
ALL = "all"
CLINIC_TRAINERS = "clinic_trainers"


def load_dataset(source: Source, config: Config, target: date) -> Dataset:
    """Read every sheet and build the Dataset for `target`.

    Each spreadsheet is fetched with as few requests as possible; over Google Sheets, one
    request per spreadsheet plus one for the metric tabs and one for past schedules.

    The cabin act sheets are a folder of their own, one per session and week, and the whole
    folder is read: they are fetched in parallel and started first, so the dozens of small
    requests they take run while the rest of the sheets are being read and parsed.
    """
    tabs = config.tabs
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        boards = pool.submit(_cabin_act_boards, source, config)
        return _build(source, config, target, tabs, warnings, boards)


def _build(source: Source, config: Config, target: date, tabs, warnings: list[str], boards):
    """Everything but the cabin act sheets, which are already on their way."""
    skills_tables = source.read_many("skills", [tabs["skills"], tabs["position_skills"]])
    staff, skill_warnings = parse_skills(skills_tables[tabs["skills"]])
    warnings += skill_warnings
    skills = known_skills(skills_tables[tabs["skills"]])
    position_skills = parse_position_skills(skills_tables[tabs["position_skills"]], skills)
    clinics = parse_clinics(source.read("clinic_data", tabs["clinics"]), position_skills, skills)
    wanted = [tabs["blocks"], tabs["calendar"], tabs["requests"], tabs["metrics"]]
    if tabs["adjustments"] in source.tabs("config"):
        wanted.append(tabs["adjustments"])  # the tab is optional
    config_tables = source.read_many("config", wanted)
    blocks = parse_blocks(config_tables[tabs["blocks"]])
    categories = {c for b in blocks.values() for c in b.categories} - {ALL_BLOCKS}
    _reserve("block", categories, (ALL_BLOCKS, *blocks))
    spans = parse_calendar(config_tables[tabs["calendar"]])
    calendar = calendar_days(spans)
    if target not in calendar:
        raise LoadError(f"Calendar: {target} is not a camp day")

    adjustments = parse_adjustments(
        config_tables.get(tabs["adjustments"], [[*ADJUSTMENT_HEADER]]), staff
    )
    resting: dict[date, dict[str, frozenset[str]]] = {}
    for a in adjustments:
        if a.date not in calendar:
            continue
        on_day = [b for b in blocks.values() if block_runs_on(b, calendar[a.date])]
        resting.setdefault(a.date, {})[a.staff] = resting_blocks(a, on_day, config.midday)
    today = {a.staff: a for a in adjustments if a.date == target}
    staff = {
        **staff,
        **{
            i: replace(staff[i], ral=a.ral_for(staff[i].ral), resting_blocks=resting[target][i])
            for i, a in today.items()
        },
    }
    # someone resting the whole day is offered by no category, so nothing is asked of them
    today_blocks = {b.id for b in blocks.values() if block_runs_on(b, calendar[target])}
    working = frozenset(i for i, member in staff.items() if member.resting_blocks != today_blocks)

    categories = parse_staff_categories(
        source.read("staff_categories", tabs["staff_categories"]), staff
    )
    _reserve("staff", categories, (ALL, CLINIC_TRAINERS, *staff))
    named = {**categories, ALL: frozenset(staff), CLINIC_TRAINERS: trainers(staff)}
    categories = named
    # a category never offers someone who is not working today
    staff_categories = {c: members & working for c, members in categories.items()}
    cabin_acts, cabin_warnings = cabin_act_activities(
        boards.result(), _weeks_by_weekday(spans), staff, named, skills
    )
    warnings += cabin_warnings
    activities = {**clinics, **cabin_acts}
    offerings, offering_warnings = parse_offerings(
        source.read("clinic_schedule", tabs["offerings"]),
        clinics,
        set(blocks),
        target.strftime("%A"),
    )
    warnings += offering_warnings
    requests = parse_requests(config_tables[tabs["requests"]])

    # Only the clinics have categories; a cabin act is found by its cabin, not by a heading.
    clinic_categories = {a.category for a in clinics.values()}
    _reserve("activity", clinic_categories, (ALL, *clinics))
    activity_categories = {
        c: frozenset(a.id for a in clinics.values() if a.category == c) for c in clinic_categories
    }

    def to_id(field: str, value: str) -> str:
        return value if field == "date" else normalize(value)

    index = metrics_sheet.parse_metric_index(config_tables[tabs["metrics"]])
    tab_of = {m.name: f"{metrics_sheet.TAB_PREFIX}{m.name}" for m in index}
    metric_tables = source.read_many("config", list(tab_of.values()))
    metrics = {
        m.name: metrics_sheet.parse_metric(m, metric_tables[tab_of[m.name]], to_id) for m in index
    }

    days = {}
    for tab in source.tabs("published"):
        try:
            day = parse_date(tab, "Published Schedules")
        except LoadError:
            continue
        if day == target or (day < target and day in calendar):
            days[tab] = day
    schedules = {
        days[tab]: parse_published(table, days[tab], staff, activities)
        for tab, table in source.read_many("published", list(days)).items()
    }
    baseline = schedules.pop(target, None)  # the target's own schedule is what to hold to

    return Dataset(
        target=target,
        staff=staff,
        staff_categories=staff_categories,
        activities=activities,
        activity_categories=activity_categories,
        blocks=blocks,
        block_categories=block_categories(blocks),
        calendar=calendar,
        spans=spans,
        offerings=offerings,
        requests=requests,
        metrics=metrics,
        published=schedules,
        baseline=baseline,
        adjustments=adjustments,
        resting=resting,
        warnings=tuple(warnings),
    )


def _reserve(namespace: str, names: Iterable[str], taken: Iterable[str]) -> None:
    """A sheet value may not normalize to a built-in name or to another value's identifier."""
    clash = set(names) & set(taken)
    if clash:
        raise LoadError(f"{namespace}: '{sorted(clash)[0]}' is already a name; rename it")


CABIN_ACTS_FOLDER = "cabin_acts"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _cabin_act_boards(source: Source, config: Config) -> dict[str, tuple]:
    """Every cabin act sheet's Board tab, parsed. No folder chosen means no cabin acts."""
    try:
        tables = source.read_group(CABIN_ACTS_FOLDER, config.tabs["cabin_act_board"])
    except LoadError:
        return {}  # the folder is optional, and an install without one has no cabin acts
    return {title: parse_board(table, title) for title, table in tables.items()}


def _weeks_by_weekday(spans: tuple[Span, ...]) -> dict[tuple[int, int], dict[str, date]]:
    """(session, week) -> that week's dates by weekday name, which is how a board finds a day.

    A cabin act sheet is titled by session and week, so only the numbered spans can hold
    one; a span that is not a session has no session number to be titled after.
    """
    weeks: dict[tuple[int, int], dict[str, date]] = {}
    for span in spans:
        if span.session is None:
            continue
        for day in span.dates:
            weeks.setdefault((span.session, span.week_of(day)), {})[WEEKDAYS[day.weekday()]] = day
    return weeks
