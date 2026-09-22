"""Requests: their own spreadsheet, one row per request, one tab per session.

They used to be a tab of the Config sheet, and that one tab held every request the season
had ever made, which meant reading the whole season to schedule one day: the generated
clinic requests alone are one row per clinic per block per day, and by August there were
thousands of them nobody would ever look at again.

They are now a spreadsheet of their own — `Requests`, beside Config and Skills in the
Puppet Strings folder, found by its name like the rest. Its tabs are these, and a load
reads three of them:

    Season Requests   what holds all season or crosses sessions: the legal limits, the
                      standing agreements, anything written for more than one session
    S1 Clinics        the clinic requests Load offerings writes for session 1's days
    S1 Special        what was asked for session 1 in particular

A span that is not a numbered session is labelled by its own name instead of `S1`, so a
`Staff Week` row on the Calendar sheet gets `Staff Week Clinics` and `Staff Week Special`.

Which tab a request lives on is its `home`, and it is read off the tab it came from. A
request written in the app goes to its session's Special tab unless it is said to hold all
season, and a generated one goes to the session's Clinics tab, where the next Load
offerings can throw it away without touching anything written by hand.
"""

import re
from datetime import date

from puppet_strings.generate import GENERATED_TAG
from puppet_strings.model import WRITABLE_PRIORITIES, Priority, Request, Span
from puppet_strings.names import normalize
from puppet_strings.sheets.calendar import parse_date
from puppet_strings.sheets.source import LoadError, Source, Table, header_rows, split_list

REQUESTS_SHEET = "requests"  # the role the Requests spreadsheet is read under
REQUESTS_TITLE = "Requests"  # what it is called in the Puppet Strings folder
SEASON_TAB = "Season Requests"  # the one tab every span's load reads
CLINICS_SUFFIX = " Clinics"
SPECIAL_SUFFIX = " Special"

COLUMNS = (
    "id",
    "description",
    "skedge",
    "priority",
    "weight",
    "tags",
    "group",
    "requester",
    "created",
)
# tags, group and requester may be left off a sheet written before they existed, and
# `description` may be left empty on any row: it is for people, and the id is the name.
OPTIONAL = ("tags", "group", "requester")
LEGACY_GROUPS = "groups"  # the column when a request could be on more than one shelf
REQUIRED = tuple(c for c in COLUMNS if c not in OPTIONAL)


def span_label(span: Span) -> str:
    """What a span's own tabs are called after: `S4` for a session, else the span's name."""
    return f"S{span.session}" if span.session is not None else span.name


def clinics_tab(span: Span) -> str:
    """The tab holding the span's generated clinic requests."""
    return f"{span_label(span)}{CLINICS_SUFFIX}"


def special_tab(span: Span) -> str:
    """The tab holding what was asked for this span in particular."""
    return f"{span_label(span)}{SPECIAL_SUFFIX}"


def request_tabs(span: Span) -> tuple[str, ...]:
    """The three tabs a load of a day in this span reads."""
    return (SEASON_TAB, clinics_tab(span), special_tab(span))


def read_requests(source: Source, span: Span) -> tuple[tuple[Request, ...], list[str]]:
    """The requests in play for a day of `span`, and anything worth saying about the read.

    A missing tab is not an error: a session nobody has written a special request for yet
    simply has no Special tab, and a write makes one when there is something to put in it.
    A missing spreadsheet is, because a season with no requests at all is far more likely
    to be a sheet nobody has split yet than a season nobody has asked anything of.
    """
    have = set(_tabs(source))
    wanted = [tab for tab in request_tabs(span) if tab in have]
    warnings: list[str] = []
    if SEASON_TAB not in have:
        warnings.append(f"{REQUESTS_TITLE}: no '{SEASON_TAB}' tab, so nothing holds all season")
    tables = source.read_many(REQUESTS_SHEET, wanted)
    return parse_request_tabs({tab: tables[tab] for tab in wanted}), warnings


def _tabs(source: Source) -> list[str]:
    """The Requests spreadsheet's tabs, or a LoadError saying how to get one."""
    try:
        return source.tabs(REQUESTS_SHEET)
    except LoadError as e:
        raise LoadError(
            f"{REQUESTS_TITLE}: no '{REQUESTS_TITLE}' spreadsheet in the Puppet Strings folder. "
            "`puppet-strings split-requests` makes one from the Config sheet's Requests tab, "
            f"a tab per session ({e})"
        ) from e


def parse_request_tabs(tables: dict[str, Table]) -> tuple[Request, ...]:
    """Requests from several tabs at once, in tab order. Ids must be unique across them all."""
    requests: list[Request] = []
    ids: set[str] = set()
    for tab, table in tables.items():
        requests += parse_requests(table, tab, ids)
    return tuple(requests)


def parse_requests(table: Table, where: str = "Requests", ids: set[str] | None = None):
    """One tab's requests in sheet order. Checks fields, not Skedge (see skedge.validate).

    `ids` is the ids already taken by the tabs read before this one; it is added to, so a
    request that appears on two tabs is caught rather than quietly shadowing the other.
    """
    rows = header_rows(table, REQUIRED, where)
    requests = []
    ids = set() if ids is None else ids
    for row in rows:
        cell = f"{where} row '{row['id']}'"
        if not row["id"]:
            raise LoadError(f"{where}: a row has no id")
        if row["id"] in ids:
            raise LoadError(f"{cell}: duplicate id")
        ids.add(row["id"])
        try:
            priority = Priority(row["priority"])
        except ValueError as e:
            allowed = [p.value for p in WRITABLE_PRIORITIES]
            raise LoadError(f"{cell}: priority must be one of {allowed}") from e
        if priority not in WRITABLE_PRIORITIES:
            raise LoadError(f"{cell}: {priority.value} is the solver's own, not a priority to set")
        weight = _weight(row["weight"], priority, cell)
        created = parse_date(row["created"], cell) if row["created"] else None
        requests.append(
            Request(
                id=row["id"],
                description=row["description"],
                skedge=row["skedge"],
                priority=priority,
                weight=weight,
                tags=tuple(split_list(row.get("tags", ""))),
                group=_group(row),
                requester=normalize(row.get("requester", "")),
                created=created,
                home=where,
            )
        )
    return tuple(requests)


def home_for(request: Request, span: Span) -> str:
    """Which tab a request belongs on: the one it names, or the one its kind implies."""
    if request.home:
        return request.home
    return clinics_tab(span) if GENERATED_TAG in request.tags else special_tab(span)


def write_requests(source: Source, requests: tuple[Request, ...], held: set[str]) -> None:
    """Write every request to the tab it calls home, and empty the tabs nothing is left on.

    `held` is the tabs the requests were read from. One of them going empty — the last
    special request of a session deleted, say — has to be written as an empty tab rather
    than left alone, or the next load reads back what was just removed.
    """
    by_tab: dict[str, list[Request]] = {tab: [] for tab in held}
    for request in requests:
        by_tab.setdefault(request.home or SEASON_TAB, []).append(request)
    # One write for the lot: saving one request rewrites up to three tabs, and a save is
    # something the Puppet Master does every couple of minutes all afternoon.
    source.write_many(
        REQUESTS_SHEET, {tab: request_rows(tuple(rows)) for tab, rows in by_tab.items()}
    )


# A generated request's id says the date it was made for: `offering:2026-09-16:riflery:...`
_GENERATED_ID = re.compile(r"^offering:(\d{4}-\d{2}-\d{2}):")


def _split_to(request: Request, by_date: dict, spans) -> str:
    """Which tab `split_requests` puts one old row on."""
    generated = _GENERATED_ID.match(request.id)
    if generated is not None:
        span = by_date.get(date.fromisoformat(generated.group(1)))
        if span is not None:
            return clinics_tab(span)
    named = _span_named(request.id, spans)
    return special_tab(named) if named is not None else SEASON_TAB


def _span_named(request_id: str, spans):
    """The span an id begins with, longest first so `session_1` cannot beat `session_1_b`.

    The id has to stop there or carry on with `-` or `_`, or `session_1` would claim
    `session_10` as well.
    """
    for span in sorted(spans, key=lambda s: len(s.id), reverse=True):
        rest = request_id[len(span.id) :]
        if request_id.startswith(span.id) and (not rest or rest[0] in "-_"):
            return span
    return None


def split_requests(source: Source, root: str, legacy: str, spans, year: int) -> dict[str, int]:
    """Make the Requests spreadsheet out of the old tab. Returns rows written per tab.

    An id says where its request goes, in one of two ways. A generated one names the date
    it was made for — `offering:2026-07-08:archery_1_2:clinic_1` — and goes to the Clinics
    tab of the span that date falls in. One that starts with a span's own id — `session_4_b-200`,
    where `_b` is the span's second week — goes to that span's Special tab.

    Anything else goes to Season Requests, which every load reads. That is the safe way to
    be unsure: a request put on the wrong session's tab would quietly stop applying and
    nobody would see it go, while one left on the season's tab is only read more often than
    it needs to be. Moving it to a session afterwards is a cut and paste.

    The Config sheet's old tab is left exactly as it was, so this can be run twice, and a
    season that turns out to have been split wrong can be split again.
    """
    by_date = {day: span for span in spans for day in span.dates}
    requests = parse_requests(source.read("config", legacy), legacy)
    by_tab: dict[str, list[Request]] = {SEASON_TAB: []}
    for request in requests:
        by_tab.setdefault(_split_to(request, by_date, spans), []).append(request)
    source.name(REQUESTS_SHEET, source.create(root, (str(year),), REQUESTS_TITLE, [SEASON_TAB]))
    for tab, rows in by_tab.items():
        source.write(REQUESTS_SHEET, tab, request_rows(tuple(rows)))
    return {tab: len(rows) for tab, rows in by_tab.items()}


def request_rows(requests: tuple[Request, ...]) -> Table:
    """Requests as a table with a header row, for writing back."""
    rows: Table = [list(COLUMNS)]
    for r in requests:
        weight = "" if r.priority.hard else _format_weight(r.weight)
        created = r.created.isoformat() if r.created else ""
        rows.append(
            [
                r.id,
                r.description,
                r.skedge,
                r.priority.value,
                weight,
                ", ".join(r.tags),
                r.group,
                r.requester,
                created,
            ]
        )
    return rows


def _group(row: dict[str, str]) -> str:
    """The one shelf a request sits on.

    A sheet written when a request could be on several has a `groups` column holding a
    comma-separated list; the first of them is the shelf now, and the rest are dropped,
    which is the only answer that does not invent a second home for it.
    """
    if row.get("group"):
        return row["group"].strip()
    listed = split_list(row.get(LEGACY_GROUPS, ""))
    return listed[0] if listed else ""


def _weight(text: str, priority: Priority, where: str) -> float:
    if not text:
        return 1.0
    if priority.hard:
        raise LoadError(f"{where}: weight is not allowed with MUST_HAPPEN")
    try:
        weight = float(text)
    except ValueError as e:
        raise LoadError(f"{where}: weight '{text}' must be a number") from e
    if weight <= 0:
        raise LoadError(f"{where}: weight must be positive")
    return weight


def _format_weight(weight: float) -> str:
    return str(int(weight)) if weight == int(weight) else str(weight)
