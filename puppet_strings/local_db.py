"""SQLite files on this computer, readable by the person who made them and nobody else.

Both hold what the sheets hold — names, skills, what was asked about whom — so they are
made the way the Google token is: in the config folder, mode 600.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY_SECONDS = 10  # how long a write waits for another thread's to finish


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    """Open a database, making it and its folder if they are not there yet.

    `readonly` opens a file somebody handed over without making or changing anything.
    """
    path = path.expanduser()
    if readonly:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    return sqlite3.connect(path, timeout=BUSY_SECONDS)


def marks(count: int) -> str:
    """The `?,?,?` an `IN (…)` or a `VALUES (…)` of `count` values takes."""
    return ",".join("?" * count)


class LocalDb:
    """One such file, made with its tables the first time it is opened.

    `SCHEMA` runs once per instance, not on every connection, so a read after the first
    opens no write transaction. A reader that must not make the file asks `exists` first.
    """

    SCHEMA = ""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self._made = False

    @property
    def exists(self) -> bool:
        """Whether there is a file yet."""
        return self.path.exists()

    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        """A connection for one piece of work: committed if it finishes, rolled back if not."""
        made = self._made and self.path.exists()
        db = connect(self.path)
        try:
            if not made:
                db.executescript(self.SCHEMA)
                self._made = True
            with db:
                yield db
        finally:
            db.close()
