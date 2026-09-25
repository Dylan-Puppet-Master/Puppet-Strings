"""A copy of the requests on Drive, in case the computer holding them is not there tomorrow.

The requests are one SQLite file on the Puppet Master's computer, and they are the one thing
Puppet Strings keeps that no sheet holds: a disk that dies, or a file deleted by mistake,
takes the season's requests with it and there is nowhere to read them back from. So a
snapshot of the file goes into `Database Backups` in the Puppet Strings folder, beside the
sheets, named for the moment it was taken.

Snapshots already there are left alone. Several of them is the point: the newest is no use
if what went wrong was a request rewritten three days ago, and a file of tens of kilobytes
is not worth pruning.

A snapshot of requests that have not changed would be a copy of a copy, so what was last
sent is fingerprinted beside the requests file and a day that writes nothing sends nothing.
The fingerprint is of the file itself, not of what Drive holds: emptying `Database Backups`
by hand is not noticed here, and the Back up button in the Configure pane is how a Puppet
Master who has done that asks for another.

Nothing here reads one back. A snapshot is a whole requests file, so taking one back is
downloading it from Drive and handing it to **Configure → Requests → Import…**, which
already refuses a file it cannot read and keeps the requests it replaces.
"""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

from puppet_strings.requests_db import SUFFIX, RequestDb
from puppet_strings.sheets.schedules import ROOT
from puppet_strings.sheets.source import CsvSource, LoadError, Source

FOLDER = "Database Backups"  # in the root folder, made the first time a backup is taken
MIME = "application/vnd.sqlite3"
STEM = "requests"
MARKER = ".backed-up"  # beside the requests file: the fingerprint of what last went to Drive


def snapshot_name(when: datetime) -> str:
    """What a backup taken at `when` is called: `requests-2026-09-24-143207.sqlite`.

    The date first, so a folder of them sorts oldest to newest, and the time to the second,
    so two taken in the same minute are two files rather than one name twice.
    """
    return f"{STEM}-{when:%Y-%m-%d-%H%M%S}{SUFFIX}"


def fingerprint(path: Path) -> str:
    """What a file holds, in one line. Two files fingerprint alike only if they are alike."""
    return sha256(path.read_bytes()).hexdigest()


def marker(book: RequestDb) -> Path:
    """Where the fingerprint of the last snapshot is kept: `requests.backed-up`."""
    return book.path.with_suffix(MARKER)


def already_backed_up(book: RequestDb) -> bool:
    """Whether the requests are as they were when the last snapshot went to Drive.

    A file that is not there has nothing to copy and counts as copied; one that has never
    been backed up, or that has been written to since, does not.
    """
    if not book.exists:
        return True
    where = marker(book)
    if not where.exists():
        return False
    try:
        return where.read_text().strip() == fingerprint(book.path)
    except OSError:
        return False  # unreadable, so take one: a needless snapshot costs a file of kilobytes


def back_up(source: Source, book: RequestDb) -> str:
    """Back up the requests, reading the account and the root folder off the source."""
    if isinstance(source, CsvSource):
        raise LoadError("a folder of fixtures carries its own requests; there is no Drive to copy")
    root = getattr(source, "folder_ids", {}).get(ROOT)
    if not root:
        raise LoadError(f"{ROOT}: no folder chosen; pick one in Configure")
    return back_up_to(source.drive, root, book)


def back_up_to(drive, root: str, book: RequestDb) -> str:
    """Put a snapshot of the requests in `Database Backups` under `root`. Returns its name.

    What is uploaded is SQLite's own backup of the file rather than a copy of its bytes, so
    it is a whole requests file however much of it was being written at the time.

    The requests are fingerprinted before the snapshot is taken and written down only once it
    has landed, so a request saved while the upload was in flight leaves the fingerprint
    saying what went, and the next backup takes that request rather than believing it sent.
    """
    if not book.exists:
        raise LoadError(f"{book.path}: there are no requests on this computer to back up")
    sent = fingerprint(book.path)
    folder = drive.folder(root, FOLDER)
    name = snapshot_name(datetime.now())
    holding = Path(mkdtemp(prefix="puppet-strings-backup-"))
    try:
        snapshot = holding / name
        book.export(snapshot)
        drive.upload(folder.id, name, snapshot, MIME)
    finally:
        rmtree(holding, ignore_errors=True)
    marker(book).write_text(f"{sent}\n")
    return name
