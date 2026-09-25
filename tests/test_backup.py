"""The requests, copied to Drive: what is sent, what it is called, and when nothing is."""

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from puppet_strings.backup import (
    FOLDER,
    MIME,
    already_backed_up,
    back_up,
    back_up_to,
    marker,
    snapshot_name,
)
from puppet_strings.drive import BOUNDARY, FOLDER_MIME, Drive, DriveError, DriveFile
from puppet_strings.model import DAY, Priority, Request, Scope
from puppet_strings.requests_db import FIXTURE_FILE, RequestDb
from puppet_strings.sheets.source import CsvSource, LoadError

ROOT_ID = "root-folder"


class FakeDrive:
    """Drive as the folders it was asked for and the files it was handed."""

    def __init__(self, refuses: bool = False) -> None:
        self.asked_for: list[tuple[str, str]] = []
        # A list, not a dict by name: Drive keeps two files of one name, so a test that
        # takes two snapshots in the same second still sees both of them.
        self.uploaded: list[tuple[str, str, bytes, str]] = []
        self.refuses = refuses

    def folder(self, parent: str, name: str) -> DriveFile:
        self.asked_for.append((parent, name))
        return DriveFile(f"{parent}/{name}", name, FOLDER_MIME)

    def upload(self, parent: str, name: str, path: Path, mime: str) -> DriveFile:
        if self.refuses:
            raise DriveError("Drive: could not upload it")
        self.uploaded.append((name, parent, path.read_bytes(), mime))
        return DriveFile(f"{parent}/{name}", name, mime)


class FakeSource:
    """As much of a SheetsSource as a backup reads: the account's Drive and the folders."""

    requests_file = None

    def __init__(self, drive: FakeDrive, folders: dict[str, str]) -> None:
        self.drive = drive
        self.folder_ids = folders


@pytest.fixture
def book(fixtures_copy) -> RequestDb:
    return RequestDb(fixtures_copy / FIXTURE_FILE)


def added(book: RequestDb, id: str = "season-9") -> None:
    """Save a request, as the Puppet Master writing one in the app does."""
    book.put(
        (
            Request(
                id,
                "",
                "REQUEST staff.dylan FREE DURING blocks.clinic_1",
                Priority.HIGH,
                scope=Scope(DAY, date(2026, 9, 16), date(2026, 9, 16)),
            ),
        )
    )


class FakeSession:
    """An authorized session as what it was asked to send, and what it says back."""

    def __init__(self, ok: bool = True) -> None:
        self.sent: dict = {}
        self.ok = ok

    def post(self, url, params=None, data=None, headers=None, timeout=None, json=None):
        self.sent = {"url": url, "params": params, "data": data, "headers": headers}
        return SimpleNamespace(
            ok=self.ok,
            text="no" if not self.ok else "",
            json=lambda: {"id": "f1", "name": params["fields"] and "sent", "mimeType": MIME},
        )


def upload_with(session: FakeSession, path: Path) -> DriveFile:
    """`Drive.upload` over a session that only remembers, so no account is needed."""
    drive = Drive.__new__(Drive)
    drive.session = session
    return drive.upload("folder-1", "requests-2026-09-24-143207.sqlite", path, MIME)


def test_an_upload_sends_the_metadata_and_the_bytes_in_one_request(tmp_path):
    """Drive takes a small file whole, as multipart: the JSON, then the file, then the end."""
    file = tmp_path / "requests.sqlite"
    file.write_bytes(b"SQLite format 3\x00the requests")
    session = FakeSession()

    upload_with(session, file)

    assert session.sent["url"].startswith("https://www.googleapis.com/upload/")
    assert session.sent["params"]["uploadType"] == "multipart"
    assert f"boundary={BOUNDARY}" in session.sent["headers"]["Content-Type"]
    body = session.sent["data"]
    assert b'"name": "requests-2026-09-24-143207.sqlite"' in body
    assert b'"parents": ["folder-1"]' in body
    assert file.read_bytes() in body
    assert body.endswith(f"\r\n--{BOUNDARY}--\r\n".encode())


def test_an_upload_drive_refuses_is_said_so(tmp_path):
    file = tmp_path / "requests.sqlite"
    file.write_bytes(b"SQLite format 3\x00")

    with pytest.raises(DriveError, match="could not upload"):
        upload_with(FakeSession(ok=False), file)


def test_a_snapshot_is_named_for_the_moment_it_was_taken():
    """The date first, so a folder of them reads oldest to newest."""
    assert snapshot_name(datetime(2026, 9, 24, 14, 32, 7)) == "requests-2026-09-24-143207.sqlite"


def held(drive: FakeDrive, which: int, folder: Path) -> list[str]:
    """The ids in one of the snapshots uploaded, read back as a requests file."""
    name, _, bytes_sent, _ = drive.uploaded[which]
    landed = folder / f"{which}-{name}"
    landed.write_bytes(bytes_sent)
    return [r.id for r in RequestDb(landed).every()]


def test_a_backup_uploads_the_requests_to_the_folder_in_the_root(book, tmp_path):
    drive = FakeDrive()

    name = back_up_to(drive, ROOT_ID, book)

    assert drive.asked_for == [(ROOT_ID, FOLDER)]
    sent_name, parent, _, mime = drive.uploaded[0]
    assert (sent_name, parent, mime) == (name, f"{ROOT_ID}/{FOLDER}", MIME)
    assert held(drive, 0, tmp_path) == [r.id for r in book.every()]


def test_a_snapshot_is_of_the_requests_as_they_were_when_it_was_taken(book, tmp_path):
    """Nothing is overwritten: the point of a snapshot is the ones taken before it."""
    drive = FakeDrive()
    back_up_to(drive, ROOT_ID, book)
    added(book, "season-9")
    back_up_to(drive, ROOT_ID, book)

    assert "season-9" not in held(drive, 0, tmp_path)
    assert "season-9" in held(drive, 1, tmp_path)


def test_requests_that_have_not_changed_are_not_sent_again(book):
    """A day that writes no requests sends nothing: the copy on Drive is already of these."""
    assert not already_backed_up(book)

    back_up_to(FakeDrive(), ROOT_ID, book)

    assert already_backed_up(book)


def test_a_saved_request_is_a_reason_to_back_up_again(book):
    back_up_to(FakeDrive(), ROOT_ID, book)
    added(book)

    assert not already_backed_up(book)


def test_a_backup_that_did_not_land_is_not_written_down(book):
    """Drive refusing leaves the requests wanting a backup, so the next load takes one."""
    with pytest.raises(DriveError):
        back_up_to(FakeDrive(refuses=True), ROOT_ID, book)

    assert not marker(book).exists()
    assert not already_backed_up(book)


def test_there_is_nothing_to_back_up_before_there_are_requests(tmp_path):
    book = RequestDb(tmp_path / "requests.sqlite")

    assert already_backed_up(book)
    with pytest.raises(LoadError, match="no requests on this computer"):
        back_up_to(FakeDrive(), ROOT_ID, book)


def test_the_root_folder_must_be_chosen(book):
    with pytest.raises(LoadError, match="no folder chosen"):
        back_up(FakeSource(FakeDrive(), {}), book)


def test_a_folder_of_fixtures_has_no_drive_to_copy_to(book, fixtures_copy):
    with pytest.raises(LoadError, match="carries its own requests"):
        back_up(CsvSource(fixtures_copy), book)


def test_a_backup_reads_the_root_folder_off_the_source(book):
    drive = FakeDrive()

    name = back_up(FakeSource(drive, {"root": ROOT_ID}), book)

    assert drive.uploaded[0][:2] == (name, f"{ROOT_ID}/{FOLDER}")
