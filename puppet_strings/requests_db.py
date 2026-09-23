"""Requests, kept on this computer in one SQLite file.

Nobody edits requests anywhere but in Puppet Strings, and only one Puppet Master schedules
at a time, so the requests are a file on that Puppet Master's computer. Export hands a copy
to the next Puppet Master; Import takes one in, keeping the requests it replaces beside it
in case they were wanted after all.

Every request has a **scope**: the day, the week, the session or the season it is read
on (`model.Scope`). A load of a date reads every request whose scope covers it, and the
solver meets them, or weighs them, as their Skedge says; a request whose scope does not
cover the date is not read at all. The scope is kept as the dates it covers, so finding a
day's requests is one question of an index however many days the season has had, and
nothing needs a list of its own per day or per session.

A request written in the app is scoped to its session unless it is scoped otherwise, and
the clinics imported from the Offerings tab are scoped to their day: they are that day's
and nobody else's, and the next Load offerings of the day can throw them away without touching
anything written by hand.

A folder of fixtures carries its own `requests.sqlite`, so a copy of a session is one
folder and running on it touches nothing on the computer it runs on.
"""

import re
import shutil
import sqlite3
from datetime import date
from itertools import count
from pathlib import Path

from puppet_strings.config import Config
from puppet_strings.generate import IMPORT_TAG
from puppet_strings.local_db import LocalDb, connect, marks
from puppet_strings.model import (
    DAY,
    SCOPES,
    SEASON,
    SESSION,
    WEEK,
    WRITABLE_PRIORITIES,
    Dataset,
    Priority,
    Request,
    Scope,
)
from puppet_strings.names import normalize
from puppet_strings.sheets.source import FIXTURE_FILE, LoadError, Source, split_list

__all__ = ["FIXTURE_FILE", "RequestDb", "open_requests"]

SUFFIX = ".sqlite"
SCHEMA_VERSION = "2"
DEFAULT_SCOPE = SESSION  # what a request written in the app is read over, unless it says
OLD_IMPORT_TAG = "generated"  # what IMPORT_TAG was called before, renamed on open
# A date name from before `dates.session.four.week.two` became `dates.session_four.week_two`
OLD_DATE_NAME = re.compile(r"\bdates\.(?:session\.|other\.)[a-z0-9_.]*")

_FIELDS = (
    "id",
    "scope",
    "first",
    "last",
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
# The version first: what the rest of the file looks like depends on it.
_META = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', '{SCHEMA_VERSION}');
"""
_TABLES = """
CREATE TABLE IF NOT EXISTS requests (
    "id" TEXT PRIMARY KEY,
    "scope" TEXT NOT NULL,
    "first" TEXT NOT NULL,
    "last" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "skedge" TEXT NOT NULL,
    "priority" TEXT NOT NULL,
    "weight" REAL NOT NULL,
    "tags" TEXT NOT NULL,
    "group" TEXT NOT NULL,
    "requester" TEXT NOT NULL,
    "created" TEXT
);
CREATE INDEX IF NOT EXISTS requests_by_date ON requests ("first", "last");
"""
# Broadest scope first, then in the order they were made; an update keeps a row's rowid.
_ORDER = (
    "ORDER BY CASE scope "
    + " ".join(f"WHEN '{kind}' THEN {i}" for i, kind in enumerate(reversed(SCOPES)))
    + " END, rowid"
)
_PUT = (
    f"INSERT INTO requests ({_COLUMNS}) VALUES ({marks(len(_FIELDS))}) "
    'ON CONFLICT ("id") DO UPDATE SET ' + ", ".join(f'"{f}" = excluded."{f}"' for f in _FIELDS[1:])
)


# -- scopes -----------------------------------------------------------------------------------


def scope_for(request: Request, dataset: Dataset) -> Scope:
    """The request's own scope, or the one its kind implies around the date scheduled."""
    if request.scope is not None:
        return request.scope
    return dataset.scope(DAY if IMPORT_TAG in request.tags else DEFAULT_SCOPE)


def describe(scope: Scope) -> str:
    """A scope as the request manager shows it: `Week: Jun 7 to Jun 13`."""
    first, last = f"{scope.first:%b} {scope.first.day}", f"{scope.last:%b} {scope.last.day}"
    if scope.kind == DAY:
        return f"Day: {scope.first:%a} {first}"
    if scope.kind == SEASON:
        return f"Season: {scope.first.year}"
    return f"{scope.kind.capitalize()}: {first} to {last}"


def id_prefix(scope: Scope, dataset: Dataset) -> str:
    """What a new request's id starts with: `season`, `s4`, `s4w2`, `jun08`."""
    if scope.kind == SEASON:
        return SEASON
    if scope.kind == DAY:
        return f"{scope.first:%b%d}".lower()
    entry = dataset.calendar.get(scope.first)
    span = next((s for s in dataset.spans if entry and s.id == entry.span), None)
    if span is None:  # dated off the calendar, which a scope made here never is
        return f"{scope.kind}{scope.first:%m%d}"
    label = f"s{span.session}" if span.session is not None else normalize(span.name)
    label = label.replace("_", "-")
    return f"{label}w{entry.week}" if scope.kind == WEEK else label


# -- the file ---------------------------------------------------------------------------------


class RequestDb(LocalDb):
    """The requests file."""

    SCHEMA = _META

    def _made(self, db: sqlite3.Connection) -> None:
        """A file from another version of the app is refused before it is read as this one."""
        _same_version(db, self.path)
        db.executescript(_TABLES)
        _retag_imports(db)
        _rename_dates(db)

    def read(self, day: date) -> tuple[Request, ...]:
        """Every request whose scope covers `day`, broadest scope first.

        A computer with no file yet has no requests; reading makes no file, so a load of a
        folder that is read-only (the trainer's) leaves it as it was.
        """
        if not self.exists:
            return ()
        with self._open() as db:
            rows = db.execute(
                f'SELECT {_COLUMNS} FROM requests WHERE "first" <= ? AND ? <= "last" {_ORDER}',
                (day.isoformat(), day.isoformat()),
            ).fetchall()
        return _requests(rows)

    def put(self, requests) -> None:
        """Add requests, or change the ones already there by id, keeping their place."""
        with self._open() as db:
            db.executemany(_PUT, [_row(r) for r in requests])

    def delete(self, ids) -> None:
        """Take requests out by id."""
        ids = list(ids)
        if ids and self.exists:
            with self._open() as db:
                db.execute(f'DELETE FROM requests WHERE "id" IN ({marks(len(ids))})', ids)

    def next_id(self, prefix: str) -> str:
        """The first id `prefix-1`, `prefix-2`, … that no request in the file has."""
        taken: set[str] = set()
        if self.exists:
            with self._open() as db:
                rows = db.execute('SELECT "id" FROM requests WHERE "id" LIKE ?', (f"{prefix}-%",))
                taken = {row[0] for row in rows}
        return next(f"{prefix}-{n}" for n in count(1) if f"{prefix}-{n}" not in taken)

    def every(self) -> tuple[Request, ...]:
        """Every request in the file, broadest scope first."""
        if not self.exists:
            return ()
        with self._open() as db:
            return _requests(db.execute(f"SELECT {_COLUMNS} FROM requests {_ORDER}").fetchall())

    def count(self) -> int:
        """How many requests the file holds; 0 if there is no file yet, which it does not make."""
        if not self.exists:
            return 0
        with self._open() as db:
            return _count(db)

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
            return _count(copy)
        finally:
            db.close()
            copy.close()

    def import_file(self, source: Path) -> tuple[int, Path | None]:
        """Replace every request with a file's. Returns how many, and where the old ones went.

        The file is checked before anything is touched: one that is not a requests file, or
        holds a row the app would refuse to load, is refused whole. The requests it replaces
        are kept beside this file, `….before-import.sqlite`, until the next import.
        """
        rows = _checked(Path(source).expanduser())
        kept = None
        if self.exists:
            kept = self.path.with_name(f"{self.path.stem}.before-import{SUFFIX}")
            shutil.copyfile(self.path, kept)
        with self._open() as db:
            db.execute("DELETE FROM requests")
            db.executemany(_PUT, rows)
            _retag_imports(db)
            _rename_dates(db)
        return len(rows), kept


def open_requests(config: Config, source: Source | None) -> RequestDb:
    """The requests file: a fixture folder's own, or else the one on this computer."""
    own = source.requests_file if source is not None else None
    return RequestDb(own or config.requests)


def _count(db) -> int:
    return db.execute("SELECT count(*) FROM requests").fetchone()[0]


def _retag_imports(db: sqlite3.Connection) -> None:
    """Rename the old `generated` tag on imported clinics to IMPORT_TAG.

    The tag is how a load knows a day's clinics are already imported, so a file from before
    the rename would otherwise import them all again on top of the old ones.
    """
    rows = db.execute(
        """SELECT "id", "tags" FROM requests WHERE "id" LIKE 'offering:%' AND "tags" LIKE ?""",
        (f"%{OLD_IMPORT_TAG}%",),
    ).fetchall()
    for id, tags in rows:
        renamed = [IMPORT_TAG if t == OLD_IMPORT_TAG else t for t in split_list(tags)]
        db.execute('UPDATE requests SET "tags" = ? WHERE "id" = ?', (", ".join(renamed), id))
    if rows:
        db.commit()


def _rename_dates(db: sqlite3.Connection) -> None:
    """Write the old nested date names the way they are written now.

    `dates.session.four.week.two.monday` is `dates.session_four.week_two.monday`, and
    `dates.other.family_camp.all` is `dates.family_camp.all`. A request from before the
    rename would otherwise stop validating the day the app is updated.
    """
    rows = db.execute(
        """SELECT "id", "skedge" FROM requests
        WHERE "skedge" LIKE '%dates.session.%' OR "skedge" LIKE '%dates.other.%'"""
    ).fetchall()
    for id, skedge in rows:
        renamed = OLD_DATE_NAME.sub(lambda m: _flat_date_name(m.group()), skedge)
        db.execute('UPDATE requests SET "skedge" = ? WHERE "id" = ?', (renamed, id))
    if rows:
        db.commit()


def _flat_date_name(name: str) -> str:
    """`dates.session.four.week.two.all` as it is written now: `dates.session_four.week_two.all`."""
    parts = name.split(".")
    flat = [parts[0]]
    rest = iter(parts[1:])
    for part in rest:
        if part == "other":
            continue
        if part in ("session", "week"):
            part = f"{part}_{next(rest, '')}".rstrip("_")
        flat.append(part)
    return ".".join(flat)


def _same_version(db: sqlite3.Connection, where: Path) -> None:
    (version,) = db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    if version == SCHEMA_VERSION:
        return
    if version.isdigit() and int(version) < int(SCHEMA_VERSION):
        raise LoadError(
            f"{where}: a requests file from an earlier version of Puppet Strings (format "
            f"{version}), which this one (format {SCHEMA_VERSION}) cannot read. Move it aside "
            "and start a new one"
        )
    raise LoadError(
        f"{where}: a requests file from a newer version of Puppet Strings (format "
        f"{version}); this one reads format {SCHEMA_VERSION}. Update Puppet Strings"
    )


# -- rows -------------------------------------------------------------------------------------


def _row(r: Request) -> tuple:
    if r.scope is None:
        raise ValueError(f"request '{r.id}' has no scope; scope it before saving it")
    return (
        r.id,
        r.scope.kind,
        r.scope.first.isoformat(),
        r.scope.last.isoformat(),
        r.description,
        r.skedge,
        r.priority.value,
        1.0 if r.priority.hard else r.weight,
        ", ".join(r.tags),
        r.group,
        r.requester,
        r.created.isoformat() if r.created else None,
    )


def _requests(rows: list[tuple]) -> tuple[Request, ...]:
    """Rows as requests, refusing one the app could not have written."""
    return tuple(_request(*row) for row in rows)


def _request(
    id, scope, first, last, description, skedge, priority, weight, tags, group, requester, created
) -> Request:
    where = f"request '{id}'"
    if not id:
        raise LoadError("a request has no id")
    if scope not in SCOPES:
        raise LoadError(f"{where}: no scope '{scope}'; a scope is one of {', '.join(SCOPES)}")
    try:
        span = Scope(scope, date.fromisoformat(first), date.fromisoformat(last))
        day = date.fromisoformat(created) if created else None
    except (TypeError, ValueError) as e:
        raise LoadError(f"{where}: a date that is not a date ({e})") from e
    try:
        level = Priority(priority)
    except ValueError as e:
        raise LoadError(f"{where}: no priority '{priority}'") from e
    if level not in WRITABLE_PRIORITIES:
        raise LoadError(f"{where}: {level.value} is the solver's own, not a priority to set")
    if not isinstance(weight, int | float) or weight <= 0:
        raise LoadError(f"{where}: weight must be a positive number, not {weight!r}")
    return Request(
        id=id,
        description=description,
        skedge=skedge,
        priority=level,
        weight=1.0 if level.hard else float(weight),
        tags=tuple(split_list(tags)),
        group=group,
        requester=requester,
        created=day,
        scope=span,
    )


def _checked(source: Path) -> list[tuple]:
    """The rows of a requests file, once it is known to be one the app can load."""
    if not source.is_file():
        raise LoadError(f"{source}: no such file")
    try:
        db = connect(source, readonly=True)
        try:
            _same_version(db, source)
            rows = db.execute(f"SELECT {_COLUMNS} FROM requests {_ORDER}").fetchall()
        finally:
            db.close()
    except (sqlite3.Error, TypeError) as e:
        raise LoadError(f"{source}: not a Puppet Strings requests file ({e})") from e
    _requests(rows)  # raises on a bad row
    return rows
