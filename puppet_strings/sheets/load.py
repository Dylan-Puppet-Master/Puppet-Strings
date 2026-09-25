"""Assemble a Dataset for one target date from every sheet."""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, time

from puppet_strings.config import Config
from puppet_strings.exclude import apply_exclusions
from puppet_strings.generate import with_offerings
from puppet_strings.model import CalendarDay, Dataset, Span, block_runs_on
from puppet_strings.requests_db import RequestDb, open_requests
from puppet_strings.sheets import mappings as mappings_sheet
from puppet_strings.sheets.adjustments import parse_adjustments, resting_blocks
from puppet_strings.sheets.blocks import ALL_BLOCKS, block_categories, parse_blocks
from puppet_strings.sheets.cabin_acts import cabin_act_activities, parse_board
from puppet_strings.sheets.calendar import calendar_days, parse_calendar
from puppet_strings.sheets.categories import parse_staff_categories
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import parse_published
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

READS_IN_FLIGHT = 3  # sheets read at once, beside the cabin act sheets
ADJUSTMENT_HEADER = ("date", "staff", "resting", "RAL_penalty", "note")
ALL = "all"
STAFF_CATEGORIES_TAB = "Categories"  # the one tab of a span's Staff Categories spreadsheet
CLINIC_TRAINERS = "clinic_trainers"


def load_dataset(
    source: Source,
    config: Config,
    target: date,
    history: bool = True,
    requests: RequestDb | None = None,
) -> Dataset:
    """Read every sheet, and the requests, and build the Dataset for `target`.

    The requests come from `requests`, or from `open_requests` when that is not given: the
    file on this computer, or a fixture folder's own.

    `history` reads what was published on the days before the target as well. Only the
    solver looks at those, and there is a spreadsheet of them per day of the season so far,
    so the request manager loads without them and `read_history` fetches them when a solve
    is about to want them.

    Each spreadsheet is fetched with as few requests as possible; over Google Sheets, one
    request per spreadsheet plus one for the mapping tabs and one for past schedules.

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
    # one worker more than the reads, for the cabin act sheets, which read_all spreads out
    with ThreadPoolExecutor(max_workers=READS_IN_FLIGHT + 1) as pool:
        boards = pool.submit(_cabin_act_boards, source, config)
        return _build(
            source,
            config,
            target,
            tabs,
            warnings,
            boards,
            config_tables,
            spans,
            calendar,
            history,
            pool,
            requests or open_requests(config, source),
        )


def _config_tables(source: Source, config: Config) -> dict:
    """Every tab of the config spreadsheet that is read, in one request."""
    tabs = config.tabs
    wanted = [tabs["blocks"], tabs["calendar"], tabs["mappings"]]
    if tabs["adjustments"] in source.tabs("config"):
        wanted.append(tabs["adjustments"])  # the tab is optional
    return source.read_many("config", wanted)


def with_standing(dataset: Dataset, midday: time) -> Dataset:
    """The dataset's staff as its adjustments and who is away leave them, from their usual.

    Someone on an adjustment today has its RAL and its resting blocks; someone away rests
    through the whole day. Nobody resting the whole day is offered by a category, so
    nothing is asked of them. The resting map gets every adjustment's date, since `holds`
    asks it rather than the staff member.

    Starts over from `usual_staff` and `named_categories`, so it can be applied again after
    the adjustments change, with nothing read. What an EXCLUDE did is dropped with the
    rest: `apply_exclusions` puts it back.
    """
    target, calendar = dataset.target, dataset.calendar
    resting: dict[date, dict[str, frozenset[str]]] = {}
    for a in dataset.adjustments:
        if a.date not in calendar:
            continue
        on_day = [b for b in dataset.blocks.values() if block_runs_on(b, calendar[a.date])]
        resting.setdefault(a.date, {})[a.staff] = resting_blocks(a, on_day, midday)
    today_blocks = frozenset(
        b.id for b in dataset.blocks.values() if block_runs_on(b, calendar[target])
    )
    for i in dataset.away:
        resting.setdefault(target, {})[i] = today_blocks
    today = {a.staff: a for a in dataset.adjustments if a.date == target}
    resting_today = resting.get(target, {})
    staff = {
        i: replace(
            member,
            ral=today[i].ral_for(member.ral) if i in today else member.ral,
            resting_blocks=resting_today.get(i, member.resting_blocks),
        )
        for i, member in dataset.usual_staff.items()
    }
    working = frozenset(i for i, member in staff.items() if member.resting_blocks != today_blocks)
    return replace(
        dataset,
        staff=staff,
        staff_categories={c: m & working for c, m in dataset.named_categories.items()},
        resting=resting,
        excluded={},
    )


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
    history: bool,
    pool: ThreadPoolExecutor,
    book: RequestDb,
):
    """Everything but the Calendar and the cabin act sheets, which are already read.

    Every read that needs nothing but the Calendar is sent at once, and the ones that need
    the span's folder listed are sent together as soon as it is: each is a round trip to
    Google, and one after another they are most of the wait on a load. The answers are
    parsed in the order they always were; only the span's folder and the Mappings index,
    which the later reads need, are looked at first.
    """
    span = next(s for s in spans if s.id == calendar[target].span)
    index = mappings_sheet.parse_mapping_index(config_tables[tabs["mappings"]])
    tab_of = {m.name: f"{mappings_sheet.TAB_PREFIX}{m.name}" for m in index}
    skills_read = pool.submit(source.read_many, "skills", [tabs["skills"], tabs["position_skills"]])
    clinics_read = pool.submit(source.read, "clinic_data", tabs["clinics"])
    listing = pool.submit(source.documents, ROOT, span_path(span))
    requests_read = pool.submit(book.read, target)
    mappings_read = pool.submit(source.read_many, "config", list(tab_of.values()))
    in_span = listing.result()
    day_sheet = day_title(span, target)
    categories_read = pool.submit(_categories_table, source, in_span, span)
    offerings_read = (
        pool.submit(source.read, in_span[day_sheet], tabs["offerings"])
        if day_sheet in in_span
        else None
    )

    skills_tables = skills_read.result()
    staff, skill_warnings = parse_skills(skills_tables[tabs["skills"]])
    warnings += skill_warnings
    skills = known_skills(skills_tables[tabs["skills"]])
    position_skills = parse_position_skills(skills_tables[tabs["position_skills"]], skills)
    clinics = parse_clinics(clinics_read.result(), position_skills, skills)
    blocks = parse_blocks(config_tables[tabs["blocks"]])
    categories = {c for b in blocks.values() for c in b.categories} - {ALL_BLOCKS}
    _reserve("block", categories, (ALL_BLOCKS, *blocks))

    adjustments = parse_adjustments(
        config_tables.get(tabs["adjustments"], [[*ADJUSTMENT_HEADER]]), staff
    )
    categories = parse_staff_categories(categories_read.result(), staff)
    _reserve("staff", categories, (ALL, CLINIC_TRAINERS, *staff))

    # Who is at camp is what the span's Staff Categories sheet says, not who has a Skills
    # row: the Skills sheet keeps everyone who ever worked here, including staff who have
    # left and staff who only come for one session. Anybody it does not name is away, which
    # is the same to the solver as resting all day -- no category offers them and no
    # position can be filled by them. `with_standing` takes them out, below.
    at_camp = frozenset().union(*categories.values()) if categories else frozenset(staff)
    away = set(staff) - at_camp
    if away:
        warnings.append(
            f"{len(away)} on the Skills sheet are in no category this span, so they are away"
        )
    named = {**categories, ALL: at_camp, CLINIC_TRAINERS: trainers(staff) & at_camp}
    read_boards, board_warnings = boards.result()
    warnings += board_warnings
    cabin_acts, cabin_warnings = cabin_act_activities(
        read_boards, _weeks_by_weekday(spans), staff, named, skills
    )
    warnings += cabin_warnings
    activities = {**clinics, **cabin_acts}
    if offerings_read is not None:
        offerings, offering_warnings = parse_offerings(
            offerings_read.result(),
            clinics,
            set(blocks),
            target.strftime("%A"),
        )
        warnings += offering_warnings
    else:
        offerings = ()
        warnings.append(
            f"{'/'.join(span_path(span))}: no '{day_sheet}' sheet yet, so nothing is offered; "
            "Load offerings makes one"
        )
    requests = requests_read.result()

    # Only the clinics have categories; a cabin act is found by its cabin, not by a heading.
    clinic_categories = {a.category for a in clinics.values()}
    _reserve("activity", clinic_categories, (ALL, *clinics))
    activity_categories = {
        c: frozenset(a.id for a in clinics.values() if a.category == c) for c in clinic_categories
    }

    mapping_tables = mappings_read.result()
    mappings = {
        m.name: mappings_sheet.parse_mapping(m, mapping_tables[tab_of[m.name]], config.date_order)
        for m in index
    }

    # Only the target's own day, unless the history is asked for: what happened on the days
    # before it is the solver's business, and reading them is a spreadsheet per day of the
    # season so far. `read_history` fetches them on the way into a solve.
    days = [d for d in sorted(calendar) if d <= target] if history else [target]
    schedules = _published(
        source, config, spans, calendar, target, staff, activities, {span.id: in_span}, days
    )
    baseline = schedules.pop(target, None)  # the target's own schedule is what to hold to

    dataset = Dataset(
        target=target,
        staff=staff,
        staff_categories=named,
        activities=activities,
        activity_categories=activity_categories,
        blocks=blocks,
        block_categories=block_categories(blocks),
        calendar=calendar,
        spans=spans,
        offerings=offerings,
        requests=requests,
        mappings=mappings,
        published=schedules,
        baseline=baseline,
        adjustments=adjustments,
        away=frozenset(away),
        usual_staff=staff,
        named_categories=named,
        warnings=tuple(warnings),
    )
    # Last, because who is away for a day is written in the requests and the requests are
    # read here: every reader of a Dataset then sees one day, with the people an EXCLUDE
    # takes out of it already out of it. The mappings are checked against that day, since
    # whether a row belongs to its set is a question about the day's own categories.
    dataset = replace(dataset, requests=with_offerings(dataset))
    dataset = apply_exclusions(with_standing(dataset, config.midday))
    mappings_sheet.check_mappings(dataset)
    return dataset


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


def _published(source, config, spans, calendar, target, staff, activities, listed, days):
    """These days' published assignments, each read from its own spreadsheet.

    A past day is a fact the target is scheduled around, so the assignment rows are what is
    read: the three views beside them are for people. Days are spread over a spreadsheet
    each, so they are fetched in parallel.

    A span's folder is listed once, not once per day in it, and `listed` carries in the one
    the caller has already listed to find the target's own day. Listing is a Drive request,
    and a season reaching the end of August has a couple of hundred days behind it; asking
    for the same folder that many times is most of the wait on a load.
    """
    wanted: dict[date, str] = {}
    by_span = {s.id: s for s in spans}
    listed = dict(listed)
    for day in days:
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


def read_history(source: Source, config: Config, dataset: Dataset) -> Dataset:
    """The dataset with every published day before the target read into it.

    Only the solver ever asks what happened on a past day: a pattern counting how many
    clinics somebody has run this session, a request that was already met earlier in its
    window. The window does not ask, so a load for the window does not read them — and
    there are as many of them as the season is old, one spreadsheet each. They are read
    here instead, on the way into a solve, where they are about to be worth having.
    """
    if dataset.published:
        return dataset  # already read; a second solve of the same day asks nobody
    before = [d for d in sorted(dataset.calendar) if d < dataset.target]
    published = _published(
        source,
        config,
        dataset.spans,
        dataset.calendar,
        dataset.target,
        dataset.staff,
        dataset.activities,
        {},
        before,
    )
    return replace(dataset, published=published)
