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


def connect(path: Path) -> sqlite3.Connection:
    """Open a database, making it and its folder if they are not there yet."""
    path = path.expanduser()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    return sqlite3.connect(path, timeout=BUSY_SECONDS)


@contextmanager
def opened(path: Path, schema: str = "") -> Iterator[sqlite3.Connection]:
    """A connection for one piece of work: committed if it finishes, rolled back if not."""
    db = connect(path)
    try:
        with db:
            for statement in filter(str.strip, schema.split(";")):
                db.execute(statement)
            yield db
    finally:
        db.close()
