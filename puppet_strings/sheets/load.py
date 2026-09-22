"""Assemble a Dataset for one target date from every sheet."""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import CalendarDay, Dataset, Span, block_runs_on
from puppet_strings.names import normalize
from puppet_strings.sheets import metrics as metrics_sheet
from puppet_strings.sheets.adjustments import parse_adjustments, resting_blocks
from puppet_strings.sheets.blocks import ALL_BLOCKS, block_categories, parse_blocks
from puppet_strings.sheets.cabin_acts import cabin_act_activities, parse_board
from puppet_strings.sheets.calendar import calendar_days, parse_calendar
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
from puppet_strings.sheets.requests import read_requests
from puppet_strings.sheets.schedules import (
    ROOT,
    STAFF_CATEGORIES,
    day_title,
    span_path,
)
from puppet_strings.sheets.skills import (
    known_skills,
    parse_position_skills,
    parse_skills,
    trainers,
)
from puppet_strings.sheets.source import LoadError, NotACampDay, Source

ADJUSTMENT_HEADER = ("date", "staff", "resting", "RAL_penalty", "note")
ALL = "all"
STAFF_CATEGORIES_TAB = "Categories"  # the one tab of a span's Staff Categories spreadsheet
CLINIC_TRAINERS = "clinic_trainers"


def load_dataset(source: Source, config: Config, target: date) -> Dataset:
    """Read every sheet and build the Dataset for `target`.

    Each spreadsheet is fetched with as few requests as possible; over Google Sheets, one
    request per spreadsheet plus one for the metric tabs and one for past schedules.

    The cabin act sheets are a folder of their own, one per session and week, and the whole
    folder is read: they are fetched in parallel, so the dozens of small requests they take
    run while the rest of the sheets are being read and parsed.

    The Calendar comes first and the target date is checked against it before anything else
    is read. A date camp is not running is the one mistake that makes everything after it
    meaningless — no block exists on it, so no request can reach it — and it is easy to make,
    because the app opens on tomorrow whatever tomorrow is.
    """
    tabs = config.tabs
    warnings: list[str] = []
    source.discover(ROOT, target.year)  # find the sheets by name before asking for any
    config_tables = _config_tables(source, config)
    spans = parse_calendar(config_tables[tabs["calendar"]], config.date_order)
    calendar = calendar_days(spans)
    check_camp_day(target, calendar)
    with ThreadPoolExecutor(max_workers=1) as pool:
        boards = pool.submit(_cabin_act_boards, source, config)
        return _build(
            source, config, target, tabs, warnings, boards, config_tables, spans, calendar
        )


def _config_tables(source: Source, config: Config) -> dict:
    """Every tab of the config spreadsheet that is read, in one request."""
    tabs = config.tabs
    # The requests are not here: which of their tabs to read depends on the span the
    # target falls in, which the Calendar in this very batch is what says.
    wanted = [tabs["blocks"], tabs["calendar"], tabs["metrics"]]
    if tabs["adjustments"] in source.tabs("config"):
        wanted.append(tabs["adjustments"])  # the tab is optional
    return source.read_many("config", wanted)


def check_camp_day(target: date, calendar: dict[date, CalendarDay]) -> None:
    """Raise NotACampDay unless the Calendar sheet covers the date. Says what to try instead."""
    if target in calendar:
        return
    if not calendar:
        raise NotACampDay("Calendar: no rows, so no date is a camp day")
    days = sorted(calendar)
    nearest = min(days, key=lambda day: (abs((day - target).days), day))
    raise NotACampDay(
        f"Calendar: {target} is not a camp day. The calendar runs {days[0]} to {days[-1]}; "
        f"the nearest camp day is {nearest}."
    )


def _build(
    source: Source,
    config: Config,
    target: date,
    tabs,
    warnings: list[str],
    boards,
    config_tables: dict,
    spans,
    calendar,
):
    """Everything but the Calendar and the cabin act sheets, which are already read."""
    skills_tables = source.read_many("skills", [tabs["skills"], tabs["position_skills"]])
    staff, skill_warnings = parse_skills(skills_tables[tabs["skills"]])
    warnings += skill_warnings
    skills = known_skills(skills_tables[tabs["skills"]])
    position_skills = parse_position_skills(skills_tables[tabs["position_skills"]], skills)
    clinics = parse_clinics(source.read("clinic_data", tabs["clinics"]), position_skills, skills)
    blocks = parse_blocks(config_tables[tabs["blocks"]])
    categories = {c for b in blocks.values() for c in b.categories} - {ALL_BLOCKS}
    _reserve("block", categories, (ALL_BLOCKS, *blocks))

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
    span = next(s for s in spans if s.id == calendar[target].span)
    in_span = source.documents(ROOT, span_path(span))
    categories = parse_staff_categories(_categories_table(source, in_span, span), staff)
    _reserve("staff", categories, (ALL, CLINIC_TRAINERS, *staff))

    # Who is at camp is what the span's Staff Categories sheet says, not who has a Skills
    # row: the Skills sheet keeps everyone who ever worked here, including staff who have
    # left and staff who only come for one session. Anybody it does not name is away, which
    # is the same to the solver as resting all day -- no category offers them and no
    # position can be filled by them.
    today_blocks = {b.id for b in blocks.values() if block_runs_on(b, calendar[target])}
    at_camp = frozenset().union(*categories.values()) if categories else frozenset(staff)
    away = set(staff) - at_camp
    staff = {
        **staff,
        **{i: replace(staff[i], resting_blocks=frozenset(today_blocks)) for i in away},
    }
    # `holds` asks the resting map rather than the staff member, so being away goes in both
    for i in away:
        resting.setdefault(target, {})[i] = frozenset(today_blocks)
    if away:
        warnings.append(
            f"{len(away)} on the Skills sheet are in no category this span, so they are away"
        )
    # someone resting the whole day is offered by no category, so nothing is asked of them
    working = frozenset(i for i, member in staff.items() if member.resting_blocks != today_blocks)
    categories = {**categories, ALL: at_camp, CLINIC_TRAINERS: trainers(staff) & at_camp}
    named = categories
    # a category never offers someone who is not working today
    staff_categories = {c: members & working for c, members in categories.items()}
    read_boards, board_warnings = boards.result()
    warnings += board_warnings
    cabin_acts, cabin_warnings = cabin_act_activities(
        read_boards, _weeks_by_weekday(spans), staff, named, skills
    )
    warnings += cabin_warnings
    activities = {**clinics, **cabin_acts}
    today = day_title(span, target)
    if today in in_span:
        offerings, offering_warnings = parse_offerings(
            source.read(in_span[today], tabs["offerings"]),
            clinics,
            set(blocks),
            target.strftime("%A"),
        )
        warnings += offering_warnings
    else:
        offerings = ()
        warnings.append(
            f"{'/'.join(span_path(span))}: no '{today}' sheet yet, so nothing is offered; "
            "Load offerings makes one"
        )
    requests, request_warnings = read_requests(source, span)
    warnings += request_warnings

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

    schedules = _published(
        source, config, spans, calendar, target, staff, activities, {span.id: in_span}
    )
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
        away=frozenset(away),
        warnings=tuple(warnings),
    )


def _reserve(namespace: str, names: Iterable[str], taken: Iterable[str]) -> None:
    """A sheet value may not normalize to a built-in name or to another value's identifier."""
    clash = set(names) & set(taken)
    if clash:
        raise LoadError(f"{namespace}: '{sorted(clash)[0]}' is already a name; rename it")


CABIN_ACTS_FOLDER = "cabin_acts"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _cabin_act_boards(source: Source, config: Config) -> tuple[dict[str, tuple], list[str]]:
    """Every cabin act sheet's Board tab, parsed, and anything that stopped one being read.

    Only the folder itself is optional: an install that has not chosen one has no cabin
    acts and nothing to say about it. Anything that goes wrong *inside* the folder — a
    `Board` tab renamed, a spreadsheet dropped in there that is not a cabin act sheet — is
    said out loud, because it takes every cabin act in camp out of the day, and the cost of
    saying nothing is that nobody notices the cabin acts are gone.
    """
    tab = config.tabs["cabin_act_board"]
    try:
        sheets = source.group(CABIN_ACTS_FOLDER)
    except LoadError:
        return {}, []  # no folder chosen, which is a way of having no cabin acts
    try:
        tables = source.read_all(sheets, tab)
    except LoadError as e:
        return {}, [f"cabin acts: no cabin act runs today, because {e}"]
    return {title: parse_board(table, title) for title, table in tables.items()}, []


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


def _categories_table(source: Source, in_span: dict[str, str], span: Span) -> list[list[str]]:
    """The span's own Staff Categories sheet. Who is on staff is a thing a session decides."""
    if STAFF_CATEGORIES not in in_span:
        raise LoadError(
            f"{'/'.join(span_path(span))}: no '{STAFF_CATEGORIES}' spreadsheet. "
            "Every span keeps its own, because who is on staff changes between them."
        )
    return source.read(in_span[STAFF_CATEGORIES], STAFF_CATEGORIES_TAB)


def _published(source, config, spans, calendar, target, staff, activities, listed):
    """Every published day up to and including the target, read from its own spreadsheet.

    A past day is a fact the target is scheduled around, so the assignment rows are what is
    read: the three views beside them are for people. Days are spread over a spreadsheet
    each, so they are fetched in parallel.

    A span's folder is listed once, not once per day in it, and `listed` carries in the one
    the caller has already listed to find the target's own day. Listing is a Drive request,
    and a season reaching the end of August has a couple of hundred days behind it; asking
    for the same folder that many times is most of the wait on every reload.
    """
    wanted: dict[date, str] = {}
    by_span = {s.id: s for s in spans}
    listed = dict(listed)
    for day in sorted(calendar):
        if day > target:
            break
        span = by_span[calendar[day].span]
        if span.id not in listed:
            listed[span.id] = source.documents(ROOT, span_path(span))
        key = listed[span.id].get(day_title(span, day))
        if key is not None:
            wanted[day] = key
    tables = source.read_all(
        {day.isoformat(): key for day, key in wanted.items()}, config.tabs["assignments"]
    )
    found = {}
    for day in wanted:
        table = tables[day.isoformat()]
        if not table:
            continue  # the sheet is there but the day has not been solved
        found[day] = parse_published(table, day, staff, activities)
    return found
