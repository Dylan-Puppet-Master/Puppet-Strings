"""Requests, kept on this computer in one SQLite file.

Nobody edits requests anywhere but in Puppet Strings, and only one Puppet Master schedules
at a time, so the requests are a file on that Puppet Master's computer. Export hands a copy
to the next Puppet Master; Import takes one in, keeping the requests it replaces beside it
in case they were wanted after all.

Every request is filed in one list, its `home`, and a load reads three of them:

    Season Requests   what holds all season or crosses sessions: the legal limits, the
                      standing agreements, anything written for more than one session
    S1 Clinics        the clinic requests Load offerings makes for session 1's days
    S1 Special        what was asked for session 1 in particular

A span that is not a numbered session is labelled by its own name instead of `S1`, so a
`Staff Week` row on the Calendar sheet gets `Staff Week Clinics` and `Staff Week Special`.
A request written in the app goes to its session's Special list unless it is said to hold
all season, and a generated one goes to the session's Clinics list, where the next Load
offerings can throw it away without touching anything written by hand.

A folder of fixtures carries its own `requests.sqlite`, so a copy of a session is one
folder and running on it touches nothing on the computer it runs on.
"""

import shutil
import sqlite3
from datetime import date
from pathlib import Path

from puppet_strings.config import Config
from puppet_strings.generate import GENERATED_TAG
from puppet_strings.local_db import connect, opened
from puppet_strings.model import WRITABLE_PRIORITIES, Priority, Request, Span
from puppet_strings.sheets.source import CsvSource, LoadError, Source

FIXTURE_FILE = "requests.sqlite"  # a fixture folder's own requests
SUFFIX = ".sqlite"
SCHEMA_VERSION = "1"
SEASON = "Season Requests"  # the one list every span's load reads
CLINICS_SUFFIX = " Clinics"
SPECIAL_SUFFIX = " Special"

_FIELDS = (
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
_COLUMNS = ", ".join(f'"{f}"' for f in _FIELDS)
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', '{SCHEMA_VERSION}');
CREATE TABLE IF NOT EXISTS requests (
    home TEXT NOT NULL,
    position INTEGER NOT NULL,
    "id" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "skedge" TEXT NOT NULL,
    "priority" TEXT NOT NULL,
    "weight" REAL NOT NULL,
    "tags" TEXT NOT NULL,
    "group" TEXT NOT NULL,
    "requester" TEXT NOT NULL,
    "created" TEXT,
    PRIMARY KEY (home, "id")
);
CREATE INDEX IF NOT EXISTS requests_by_home ON requests (home, position)
"""
_INSERT = (
    f"INSERT INTO requests (home, position, {_COLUMNS}) "
    f"VALUES ({','.join('?' * (len(_FIELDS) + 2))})"
)


# -- lists ------------------------------------------------------------------------------------


def span_label(span: Span) -> str:
    """What a span's own lists are called after: `S4` for a session, else the span's name."""
    return f"S{span.session}" if span.session is not None else span.name


def clinics_list(span: Span) -> str:
    """The list holding the span's generated clinic requests."""
    return f"{span_label(span)}{CLINICS_SUFFIX}"


def special_list(span: Span) -> str:
    """The list holding what was asked for this span in particular."""
    return f"{span_label(span)}{SPECIAL_SUFFIX}"


def request_lists(span: Span) -> tuple[str, ...]:
    """The three lists a load of a day in this span reads."""
    return (SEASON, clinics_list(span), special_list(span))


def home_for(request: Request, span: Span) -> str:
    """Which list a request belongs in: the one it names, or the one its kind implies."""
    if request.home:
        return request.home
    return clinics_list(span) if GENERATED_TAG in request.tags else special_list(span)


# -- the file ---------------------------------------------------------------------------------


class RequestDb:
    """The requests file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()

    def _open(self):
        return opened(self.path, _SCHEMA)

    def read(self, span: Span) -> tuple[Request, ...]:
        """The requests in the season's list and `span`'s own, each list in order.

        A computer with no file yet has no requests; reading makes no file, so a load of a
        folder that is read-only (the trainer's) leaves it as it was.
        """
        if not self.path.exists():
            return ()
        homes = request_lists(span)
        marks = ",".join("?" * len(homes))
        with self._open() as db:
            rows = db.execute(
                f"SELECT home, {_COLUMNS} FROM requests WHERE home IN ({marks}) ORDER BY position",
                homes,
            ).fetchall()
        order = {home: i for i, home in enumerate(homes)}
        requests = _requests(sorted(rows, key=lambda row: order[row[0]]))
        _unique(requests, "a load")
        return requests

    def write(self, requests: tuple[Request, ...], held: set[str]) -> None:
        """Every request to its list, and the lists in `held` emptied of anything else.

        `held` is the lists the requests were read from; one going empty — the last special
        request of a session deleted — is emptied here rather than left as it was. The
        lists a load did not read are not touched: the other sessions' requests are not in
        `requests`, and are not being deleted.
        """
        homes = set(held) | {r.home or SEASON for r in requests}
        with self._open() as db:
            db.executemany("DELETE FROM requests WHERE home = ?", [(h,) for h in homes])
            db.executemany(_INSERT, _rows(requests))

    def every(self) -> tuple[Request, ...]:
        """Every request in the file, each list's in order."""
        if not self.path.exists():
            return ()
        with self._open() as db:
            rows = db.execute(
                f"SELECT home, {_COLUMNS} FROM requests ORDER BY home, position"
            ).fetchall()
        return _requests(rows)

    def count(self) -> int:
        """How many requests the file holds; 0 if there is no file yet, which it does not make."""
        if not self.path.exists():
            return 0
        with self._open() as db:
            return db.execute("SELECT count(*) FROM requests").fetchone()[0]

    def export(self, target: Path) -> int:
        """Write a copy of the file for another Puppet Master. Returns how many it holds."""
        target = Path(target).expanduser()
        target.unlink(missing_ok=True)
        with self._open():
            pass  # a file with nothing in it yet still exports as a requests file
        # outside that connection's transaction, which a backup would wait on forever
        db, copy = connect(self.path), connect(target)
        try:
            db.backup(copy)
        finally:
            db.close()
            copy.close()
        return self.count()

    def import_file(self, source: Path) -> tuple[int, Path | None]:
        """Replace every request with a file's. Returns how many, and where the old ones went.

        The file is checked before anything is touched: one that is not a requests file, or
        holds a row the app would refuse to load, is refused whole. The requests it replaces
        are kept beside this file, `….before-import.sqlite`, until the next import.
        """
        rows = _checked(Path(source).expanduser())
        kept = None
        if self.path.exists():
            kept = self.path.with_name(f"{self.path.stem}.before-import{SUFFIX}")
            shutil.copyfile(self.path, kept)
        with self._open() as db:
            db.execute("DELETE FROM requests")
            db.executemany(_INSERT, rows)
        return len(rows), kept


def open_requests(config: Config, source: Source) -> RequestDb:
    """The requests file: the one on this computer, or a fixture folder's own."""
    if isinstance(source, CsvSource):
        return RequestDb(source.root / FIXTURE_FILE)
    return RequestDb(config.requests)


# -- rows -------------------------------------------------------------------------------------


def _rows(requests: tuple[Request, ...]) -> list[tuple]:
    """Requests as rows, each at its position among those given."""
    return [
        (
            r.home or SEASON,
            i,
            r.id,
            r.description,
            r.skedge,
            r.priority.value,
            1.0 if r.priority.hard else r.weight,
            ", ".join(r.tags),
            r.group,
            r.requester,
            r.created.isoformat() if r.created else None,
        )
        for i, r in enumerate(requests)
    ]


def _requests(rows: list[tuple]) -> tuple[Request, ...]:
    """Rows as requests, refusing one the app could not have written."""
    return tuple(_request(*row) for row in rows)


def _request(home, id, description, skedge, priority, weight, tags, group, requester, created):
    where = f"{home}, request '{id}'"
    if not id:
        raise LoadError(f"{home}: a request has no id")
    try:
        level = Priority(priority)
    except ValueError as e:
        raise LoadError(f"{where}: no priority '{priority}'") from e
    if level not in WRITABLE_PRIORITIES:
        raise LoadError(f"{where}: {level.value} is the solver's own, not a priority to set")
    if not isinstance(weight, int | float) or weight <= 0:
        raise LoadError(f"{where}: weight must be a positive number, not {weight!r}")
    try:
        day = date.fromisoformat(created) if created else None
    except ValueError as e:
        raise LoadError(f"{where}: created '{created}' is not a date") from e
    return Request(
        id=id,
        description=description,
        skedge=skedge,
        priority=level,
        weight=1.0 if level.hard else float(weight),
        tags=tuple(t.strip() for t in tags.split(",") if t.strip()),
        group=group,
        requester=requester,
        created=day,
        home=home,
    )


def _unique(requests: tuple[Request, ...], where: str) -> None:
    """Ids read together must differ, or one request would quietly shadow another."""
    seen: dict[str, str] = {}
    for r in requests:
        if r.id in seen:
            raise LoadError(f"request '{r.id}' is in both {seen[r.id]} and {r.home}, for {where}")
        seen[r.id] = r.home


def _checked(source: Path) -> list[tuple]:
    """The rows of a requests file, once it is known to be one the app can load."""
    if not source.is_file():
        raise LoadError(f"{source}: no such file")
    try:
        db = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        try:
            (schema,) = db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            rows = db.execute(
                f"SELECT home, position, {_COLUMNS} FROM requests ORDER BY home, position"
            ).fetchall()
        finally:
            db.close()
    except (sqlite3.Error, TypeError) as e:
        raise LoadError(f"{source}: not a Puppet Strings requests file ({e})") from e
    if schema != SCHEMA_VERSION:
        raise LoadError(
            f"{source}: a requests file from another version of Puppet Strings "
            f"(format {schema}, this one reads {SCHEMA_VERSION}); update the older copy"
        )
    _requests([(home, *fields) for home, _, *fields in rows])  # raises on a bad row
    return rows
