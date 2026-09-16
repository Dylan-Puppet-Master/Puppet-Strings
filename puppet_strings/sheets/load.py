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
    """Read every sheet and build the Dataset for `target`."""
    tabs = config.tabs
    warnings: list[str] = []

    staff, skill_warnings = parse_skills(source.read("skills", tabs["skills"]))
    warnings += skill_warnings
    position_skills = parse_position_skills(source.read("skills", tabs["position_skills"]))
    activities = parse_clinics(source.read("clinic_data", tabs["clinics"]), position_skills)
    staff_categories = parse_staff_categories(
        source.read("staff_categories", tabs["staff_categories"]), staff
    )
    staff_categories = {
        **staff_categories,
        ALL_STAFF: frozenset(staff),
        CLINIC_TRAINERS: staff_categories.get(CLINIC_TRAINERS, trainers(staff)),
    }
    blocks = parse_blocks(source.read("config", tabs["blocks"]))
    calendar = parse_calendar(source.read("config", tabs["calendar"]))
    if target not in calendar:
        raise LoadError(f"Calendar: {target} is not a camp day")
    offerings, offering_warnings = parse_offerings(
        source.read("clinic_schedule", tabs["offerings"]),
        activities,
        set(blocks),
        target.strftime("%A"),
    )
    warnings += offering_warnings
    requests = parse_requests(source.read("config", tabs["requests"]))

    activity_categories = {
        ANY_CLINIC: frozenset(activities),
        **{
            c: frozenset(a.id for a in activities.values() if a.category == c)
            for c in {a.category for a in activities.values()}
        },
    }

    def to_id(field: str, value: str) -> str:
        return value if field == "date" else normalize(value)

    metrics = {}
    for name, keys, low, high in metrics_sheet.parse_metric_index(
        source.read("config", tabs["metrics"])
    ):
        table = source.read("config", f"{metrics_sheet.TAB_PREFIX}{name}")
        metrics[name] = metrics_sheet.parse_metric(name, keys, low, high, table, to_id)

    session = calendar[target].session
    published = {}
    for tab in source.tabs("published"):
        try:
            day = parse_date(tab, "Published Schedules")
        except LoadError:
            continue
        if day >= target or calendar.get(day) is None or calendar[day].session != session:
            continue
        published[day] = parse_published(source.read("published", tab), day, staff, activities)

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
