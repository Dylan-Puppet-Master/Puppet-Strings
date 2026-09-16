"""Assemble a Dataset for one target date from every sheet."""

from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.names import normalize
from puppet_strings.sheets import metrics as metrics_sheet
from puppet_strings.sheets.blocks import block_categories, parse_blocks
from puppet_strings.sheets.calendar import parse_calendar, parse_date
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
from puppet_strings.sheets.requests import parse_requests
from puppet_strings.sheets.skills import parse_position_skills, parse_skills, trainers
from puppet_strings.sheets.source import LoadError, Source

ALL_STAFF = "all"
CLINIC_TRAINERS = "clinic_trainers"
ANY_CLINIC = "any_clinic"


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
    staff_categories = parse_staff_categories(
        source.read("staff_categories", tabs["staff_categories"]), staff
    )
    staff_categories = {
        **staff_categories,
        ALL_STAFF: frozenset(staff),
        CLINIC_TRAINERS: staff_categories.get(CLINIC_TRAINERS, trainers(staff)),
    }
    config_tables = source.read_many(
        "config", [tabs["blocks"], tabs["calendar"], tabs["requests"], tabs["metrics"]]
    )
    blocks = parse_blocks(config_tables[tabs["blocks"]])
    calendar = parse_calendar(config_tables[tabs["calendar"]])
    if target not in calendar:
        raise LoadError(f"Calendar: {target} is not a camp day")
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
    metric_tables = source.read_many(
        "config", [f"{metrics_sheet.TAB_PREFIX}{name}" for name, *_ in index]
    )
    metrics = {}
    for name, keys, low, high in index:
        table = metric_tables[f"{metrics_sheet.TAB_PREFIX}{name}"]
        metrics[name] = metrics_sheet.parse_metric(name, keys, low, high, table, to_id)

    session = calendar[target].session
    past_tabs = {}
    for tab in source.tabs("published"):
        try:
            day = parse_date(tab, "Published Schedules")
        except LoadError:
            continue
        if day < target and calendar.get(day) is not None and calendar[day].session == session:
            past_tabs[tab] = day
    published = {
        past_tabs[tab]: parse_published(table, past_tabs[tab], staff, activities)
        for tab, table in source.read_many("published", list(past_tabs)).items()
    }

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
        published=published,
        warnings=tuple(warnings),
    )
