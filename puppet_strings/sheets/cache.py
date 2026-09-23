"""The tabs of Google spreadsheets, kept on disk until Drive says the spreadsheet changed.

Every spreadsheet carries a `version`, a number Drive raises on every edit, and the folder
listings a load already makes return it for everything in the folder at no extra cost. A
tab read at one version is the same tab until the version moves, so a load reads again
only what somebody has changed since: a published day from last week, a cabin act board
from another session, a Skills sheet nobody has touched since Tuesday all come off disk.

What the version cannot promise is that it moves the instant an edit lands; Drive may
take a moment to count one. A spreadsheet edited and reloaded within that moment can come
back as it was. Clearing the cache (Configure, or `--no-cache`) reads everything afresh.
What Puppet Strings writes itself is never at risk: a write drops what was kept of that
spreadsheet, before Drive has had a chance to be slow about it.
"""

import json
from pathlib import Path

from puppet_strings.local_db import opened

DEFAULT_PATH = Path("~/.config/puppet_strings/sheets-cache.sqlite")
TABS = "\x00tabs"  # where a spreadsheet's list of tab names is kept, beside its tabs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tabs (
    sheet TEXT NOT NULL,
    tab TEXT NOT NULL,
    version TEXT NOT NULL,
    rows TEXT NOT NULL,
    PRIMARY KEY (sheet, tab)
)
"""


class SheetCache:
    """Tables by spreadsheet id and tab, each good for the version it was read at."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path).expanduser()

    def _open(self):
        return opened(self.path, _SCHEMA)

    def get(self, sheet: str, version: str, tabs: list[str]) -> dict[str, list] | None:
        """Every one of these tabs as read at this version, or None if any is not kept."""
        marks = ",".join("?" * len(tabs))
        with self._open() as db:
            found = dict(
                db.execute(
                    "SELECT tab, rows FROM tabs "
                    f"WHERE sheet = ? AND version = ? AND tab IN ({marks})",
                    (sheet, version, *tabs),
                ).fetchall()
            )
        if len(found) != len(set(tabs)):
            return None
        return {tab: json.loads(found[tab]) for tab in tabs}

    def put(self, sheet: str, version: str, tables: dict[str, list]) -> None:
        """Keep these tabs as read at this version, in place of any older reading."""
        with self._open() as db:
            db.executemany(
                "INSERT OR REPLACE INTO tabs (sheet, tab, version, rows) VALUES (?, ?, ?, ?)",
                [(sheet, tab, version, json.dumps(rows)) for tab, rows in tables.items()],
            )

    def drop(self, sheet: str) -> None:
        """Forget everything kept of one spreadsheet."""
        if self.path.exists():
            with self._open() as db:
                db.execute("DELETE FROM tabs WHERE sheet = ?", (sheet,))

    def clear(self) -> None:
        """Forget everything, so the next load reads every sheet from Google."""
        if self.path.exists():
            with self._open() as db:
                db.execute("DELETE FROM tabs")
