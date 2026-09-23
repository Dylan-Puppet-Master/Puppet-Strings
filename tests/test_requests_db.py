"""The requests file: what a load reads, what a save writes, and handing it over."""

import os
import shutil
import sqlite3
import sys
from dataclasses import replace
from datetime import date

import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.requests_db import FIXTURE_FILE, SEASON, RequestDb
from puppet_strings.sheets.source import LoadError
from tests.conftest import FIXTURES


@pytest.fixture
def book(tmp_path) -> RequestDb:
    copy = tmp_path / FIXTURE_FILE
    shutil.copyfile(FIXTURES / FIXTURE_FILE, copy)
    return RequestDb(copy)


def request(id, home, **fields) -> Request:
    skedge = "REQUEST staff.dylan FREE DURING blocks.clinic_1"
    return Request(id, "", skedge, fields.pop("priority", Priority.HIGH), home=home, **fields)


def test_a_load_reads_the_season_then_the_span(book, dataset):
    requests = book.read(dataset.this_span, dataset.target)
    assert [r.home for r in requests[:2]] == [SEASON, SEASON]
    assert requests[-1].home == "2026-09-16 Clinics"  # read after the season's
    first = requests[0]
    assert first.id == "counselor-hours" and first.weight == 1.0
    assert first.created == date(2026, 9, 1)
    assert first.tags == ("legal", "counselors")
    assert first.group == "Special daily requests" and first.requester == "lucy"
    assert requests[3].weight == 0.5
    assert requests[-1].tags == ("generated",) and requests[-1].group == ""


def test_every_field_round_trips(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    written = (
        request("a", SEASON, weight=2.5, tags=("x", "y z"), group="G", requester="rob"),
        request("b", "S1 Special", priority=Priority.MUST_HAPPEN, created=date(2026, 9, 2)),
    )
    book.write(written, set())
    assert book.every() == (written[1], written[0])  # by list, then in order


def test_no_file_is_no_requests_and_reading_makes_none(tmp_path, dataset):
    book = RequestDb(tmp_path / "none.sqlite")
    assert (
        book.read(dataset.this_span, dataset.target) == ()
        and book.count() == 0
        and book.every() == ()
    )
    assert not book.path.exists()  # the trainer's data folder is not written to


def test_a_write_replaces_only_the_lists_it_was_given(tmp_path, dataset):
    book = RequestDb(tmp_path / "r.sqlite")
    other = request("s2-1", "S2 Special")
    book.write((request("season-1", SEASON), request("s1-1", "S1 Special"), other), set())
    book.write((request("season-2", SEASON), request("season-1", SEASON)), {SEASON, "S1 Special"})
    assert [r.id for r in book.read(dataset.this_span, dataset.target)] == ["season-2", "season-1"]
    assert other in book.every()  # another session's list was not read, so not touched


def test_a_hard_request_is_kept_at_weight_one(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.write((request("x", SEASON, priority=Priority.MUST_HAPPEN, weight=3.0),), set())
    assert book.every()[0].weight == 1.0


def test_an_id_in_two_lists_read_together_is_refused(tmp_path, dataset):
    book = RequestDb(tmp_path / "r.sqlite")
    book.write((request("x", SEASON), request("x", "S1 Special")), set())
    with pytest.raises(LoadError, match="'x' is in both Season Requests and S1 Special"):
        book.read(dataset.this_span, dataset.target)


def test_the_solvers_own_priority_is_refused(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.write((request("x", SEASON),), set())
    with sqlite3.connect(book.path) as db:
        db.execute("UPDATE requests SET priority = 'STABILITY'")
    with pytest.raises(LoadError, match="STABILITY is the solver's own"):
        book.every()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no mode bits to speak of")
def test_the_file_is_the_puppet_masters_alone(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.write((request("x", SEASON),), set())
    assert os.stat(book.path).st_mode & 0o777 == 0o600


def test_export_and_import_hand_the_requests_over(book, tmp_path):
    handed = tmp_path / "handed.sqlite"
    assert book.export(handed) == 31
    theirs = RequestDb(tmp_path / "theirs.sqlite")
    theirs.write((request("mine", SEASON),), set())
    count, kept = theirs.import_file(handed)
    assert count == 31 and theirs.every() == book.every()
    assert kept == tmp_path / "theirs.before-import.sqlite"
    assert [r.id for r in RequestDb(kept).every()] == ["mine"]  # what was replaced is kept


def test_an_import_into_a_computer_with_no_requests_keeps_nothing(book, tmp_path):
    fresh = RequestDb(tmp_path / "fresh.sqlite")
    assert fresh.import_file(book.path) == (31, None)


@pytest.mark.parametrize("problem", ["not a database", "no meta", "newer format", "bad row"])
def test_an_import_that_would_not_load_changes_nothing(book, tmp_path, problem):
    file = tmp_path / "file.sqlite"
    if problem == "not a database":
        file.write_text("id,description\n")
    else:
        book.export(file)
        with sqlite3.connect(file) as db:
            if problem == "no meta":
                db.execute("DROP TABLE meta")
            elif problem == "newer format":
                db.execute("UPDATE meta SET value = '2'")
            else:
                db.execute("UPDATE requests SET weight = -1 WHERE id = 'breaks'")
    mine = RequestDb(tmp_path / "mine.sqlite")
    mine.write((request("mine", SEASON),), set())
    with pytest.raises(LoadError):
        mine.import_file(file)
    assert [r.id for r in mine.every()] == ["mine"]
    assert not (tmp_path / "mine.before-import.sqlite").exists()


def test_a_request_saved_in_the_app_is_in_the_file(fixtures_copy):
    from puppet_strings.app.store import RequestStore
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, TARGET, saved_requests

    store = RequestStore(CsvSource(fixtures_copy), CONFIG)
    store.load(TARGET)
    saved = store.save(replace(request("", ""), description="new"), None)
    assert saved.id == "s1-1" and saved.home == "S1 Special"
    assert saved_requests(fixtures_copy, "S1 Special")["s1-1"].description == "new"
    store.delete("s1-1")
    assert saved_requests(fixtures_copy, "S1 Special") == {}  # the emptied list is emptied


def test_one_days_offerings_are_not_another_days(tmp_path, dataset):
    """Offerings are the day's own, so a load of the next day does not show them."""
    book = RequestDb(tmp_path / "r.sqlite")
    today, tomorrow = dataset.target, date(2026, 9, 17)
    offering = request("offering:2026-09-16:riflery:clinic_1", "2026-09-16 Clinics")
    book.write((offering, request("s1-1", "S1 Special")), set())
    assert offering in book.read(dataset.this_span, today)
    assert [r.id for r in book.read(dataset.this_span, tomorrow)] == ["s1-1"]
