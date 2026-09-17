"""Assemble a Dataset for one target date from every sheet."""

from dataclasses import replace
from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.names import normalize
from puppet_strings.sheets import metrics as metrics_sheet
from puppet_strings.sheets.adjustments import on_date, parse_adjustments, resting_blocks
from puppet_strings.sheets.blocks import block_categories, parse_blocks
from puppet_strings.sheets.calendar import parse_calendar, parse_date
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
from puppet_strings.sheets.requests import parse_requests
from puppet_strings.sheets.skills import parse_position_skills, parse_skills, trainers
from puppet_strings.sheets.source import LoadError, Source

ADJUSTMENT_HEADER = ("date", "staff", "resting", "RAL_penalty", "note")
ALL_STAFF = "all"
CLINIC_TRAINERS = "clinic_trainers"
ANY_CLINIC = "any_clinic"


def _adjusted(member, adjustment, blocks, midday):
    """A staff member as they stand today: a lowered RAL, and the blocks they rest through."""
    return replace(
        member,
        ral=adjustment.ral_for(member.ral),
        resting_blocks=resting_blocks(adjustment, blocks, midday),
    )


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
    calendar = parse_calendar(config_tables[tabs["calendar"]])
    if target not in calendar:
        raise LoadError(f"Calendar: {target} is not a camp day")
    today_blocks = [b for b in blocks.values() if calendar[target].day_type in b.day_types]

    adjustments = parse_adjustments(
        config_tables.get(tabs["adjustments"], [[*ADJUSTMENT_HEADER]]), staff
    )
    today = on_date(adjustments, target)
    rested = {a.staff: _adjusted(staff[a.staff], a, today_blocks, config.midday) for a in today}
    staff = {**staff, **rested}
    # someone resting the whole day is not offered by any category, so nothing is asked of them
    off = {i for i, member in staff.items() if len(member.resting_blocks) == len(today_blocks)}
    working = frozenset(staff) - off

    categories = parse_staff_categories(
        source.read("staff_categories", tabs["staff_categories"]), staff
    )
    categories = {
        **categories,
        ALL_STAFF: frozenset(staff),
        CLINIC_TRAINERS: categories.get(CLINIC_TRAINERS, trainers(staff)),
    }
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

    activity_categories = {
        ANY_CLINIC: frozenset(activities),
        **{
            c: frozenset(a.id for a in activities.values() if a.category == c)
            for c in {a.category for a in activities.values()}
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

    session = calendar[target].session
    days = {}
    for tab in source.tabs("published"):
        try:
            day = parse_date(tab, "Published Schedules")
        except LoadError:
            continue
        in_session = calendar.get(day) is not None and calendar[day].session == session
        if day == target or (day < target and in_session):
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
        warnings=tuple(warnings),
    )
