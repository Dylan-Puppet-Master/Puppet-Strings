"""Assemble a Dataset for one target date from every sheet."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.names import normalize
from puppet_strings.sheets import metrics as metrics_sheet
from puppet_strings.sheets.adjustments import parse_adjustments, resting_blocks
from puppet_strings.sheets.blocks import ALL_BLOCKS, block_categories, parse_blocks
from puppet_strings.sheets.calendar import parse_calendar, parse_date
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
from puppet_strings.sheets.requests import parse_requests
from puppet_strings.sheets.skills import parse_position_skills, parse_skills, trainers
from puppet_strings.sheets.source import LoadError, Source

ADJUSTMENT_HEADER = ("date", "staff", "resting", "RAL_penalty", "note")
ALL = "all"
CLINIC_TRAINERS = "clinic_trainers"
DATE_SCOPES = ("target", "session", "season")


def load_dataset(source: Source, config: Config, target: date) -> Dataset:
    """Read every sheet and build the Dataset for `target`.

    Each spreadsheet is fetched with as few requests as possible; over Google Sheets, one
    request per spreadsheet plus one for the metric tabs and one for past schedules.
    """
    tabs = config.tabs
    warnings: list[str] = []

    skills_tables = source.read_many("skills", [tabs["skills"], tabs["position_skills"]])
    staff, skill_warnings = parse_skills(skills_tables[tabs["skills"]])
    warnings += skill_warnings
    position_skills = parse_position_skills(skills_tables[tabs["position_skills"]])
    activities = parse_clinics(source.read("clinic_data", tabs["clinics"]), position_skills)
    wanted = [tabs["blocks"], tabs["calendar"], tabs["requests"], tabs["metrics"]]
    if tabs["adjustments"] in source.tabs("config"):
        wanted.append(tabs["adjustments"])  # the tab is optional
    config_tables = source.read_many("config", wanted)
    blocks = parse_blocks(config_tables[tabs["blocks"]])
    categories = {c for b in blocks.values() for c in b.categories} - {ALL_BLOCKS}
    _reserve("block", categories, (ALL_BLOCKS, *blocks))
    calendar = parse_calendar(config_tables[tabs["calendar"]])
    if target not in calendar:
        raise LoadError(f"Calendar: {target} is not a camp day")
    _reserve("date", {day.session for day in calendar.values()}, DATE_SCOPES)

    adjustments = parse_adjustments(
        config_tables.get(tabs["adjustments"], [[*ADJUSTMENT_HEADER]]), staff
    )
    resting: dict[date, dict[str, frozenset[str]]] = {}
    for a in adjustments:
        if a.date not in calendar:
            continue
        day_type = calendar[a.date].day_type
        on_day = [b for b in blocks.values() if day_type in b.day_types]
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
    today_blocks = {b.id for b in blocks.values() if calendar[target].day_type in b.day_types}
    working = frozenset(i for i, member in staff.items() if member.resting_blocks != today_blocks)

    categories = parse_staff_categories(
        source.read("staff_categories", tabs["staff_categories"]), staff
    )
    _reserve("staff", categories, (ALL, CLINIC_TRAINERS, *staff))
    categories = {**categories, ALL: frozenset(staff), CLINIC_TRAINERS: trainers(staff)}
    # a category never offers someone who is not working today
    staff_categories = {c: members & working for c, members in categories.items()}
    offerings, offering_warnings = parse_offerings(
        source.read("clinic_schedule", tabs["offerings"]),
        activities,
        set(blocks),
        target.strftime("%A"),
    )
    warnings += offering_warnings
    requests = parse_requests(config_tables[tabs["requests"]])

    clinic_categories = {a.category for a in activities.values()}
    _reserve("activity", clinic_categories, (ALL, *activities))
    activity_categories = {
        ALL: frozenset(activities),
        **{
            c: frozenset(a.id for a in activities.values() if a.category == c)
            for c in clinic_categories
        },
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
