"""The requests file: what a load reads, what a save writes, and handing it over."""

import os
import sqlite3
import sys
from datetime import date

import pytest

from puppet_strings.model import DAY, SEASON, SESSION, WEEK, Priority, Request, Scope
from puppet_strings.requests_db import FIXTURE_FILE, RequestDb, describe, id_prefix, scope_for
from puppet_strings.sheets.source import LoadError

SEASON_2026 = Scope(SEASON, date(2026, 1, 1), date(2026, 12, 31))


@pytest.fixture
def book(fixtures_copy) -> RequestDb:
    return RequestDb(fixtures_copy / FIXTURE_FILE)


def day(d: date) -> Scope:
    return Scope(DAY, d, d)


def request(id, scope=SEASON_2026, **fields) -> Request:
    skedge = "REQUEST staff.dylan FREE DURING blocks.clinic_1"
    description, priority = fields.pop("description", ""), fields.pop("priority", Priority.HIGH)
    return Request(id, description, skedge, priority, scope=scope, **fields)


def test_a_load_reads_what_covers_the_day_broadest_first(book, dataset):
    requests = book.read(dataset.target)
    assert [r.scope.kind for r in requests[:7]] == [SEASON] * 7
    assert {r.scope for r in requests[7:]} == {day(dataset.target)}
    first = requests[0]
    assert first.id == "counselor-hours" and first.weight == 1.0
    assert first.created == date(2026, 9, 1)
    assert first.tags == ("legal", "counselors")
    assert first.group == "Special daily requests" and first.requester == "lucy"
    assert requests[3].weight == 0.5
    assert requests[-1].tags == ("clinic_import",) and requests[-1].group == ""


def test_a_scope_is_read_on_every_day_it_covers_and_no_other(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    week = Scope(WEEK, date(2026, 9, 13), date(2026, 9, 19))
    book.put(
        (
            request("season-1"),
            request("s1w1-1", week),
            request("sep16-1", day(date(2026, 9, 16))),
            request("last-year", Scope(SEASON, date(2025, 1, 1), date(2025, 12, 31))),
        )
    )

    def ids(d: date) -> list[str]:
        return [r.id for r in book.read(d)]

    assert ids(date(2026, 9, 16)) == ["season-1", "s1w1-1", "sep16-1"]
    assert ids(date(2026, 9, 13)) == ["season-1", "s1w1-1"]  # a scope includes its ends
    assert ids(date(2026, 9, 19)) == ["season-1", "s1w1-1"]
    assert ids(date(2026, 9, 20)) == ["season-1"]
    assert ids(date(2025, 7, 1)) == ["last-year"]


def test_every_field_round_trips(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    written = (
        request("a", weight=2.5, tags=("x", "y z"), group="G", requester="rob"),
        request(
            "b", day(date(2026, 9, 2)), priority=Priority.MUST_HAPPEN, created=date(2026, 9, 2)
        ),
    )
    book.put(written)
    assert book.every() == written  # broadest scope first


def test_a_put_changes_a_request_in_place_and_a_delete_takes_it_out(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.put((request("a"), request("b"), request("c")))
    book.put((request("a", description="changed"),))
    assert [(r.id, r.description) for r in book.every()] == [("a", "changed"), ("b", ""), ("c", "")]
    book.delete(["b"])
    assert [r.id for r in book.every()] == ["a", "c"]


def test_no_file_is_no_requests_and_reading_makes_none(tmp_path):
    book = RequestDb(tmp_path / "none.sqlite")
    assert book.read(date(2026, 9, 16)) == () and book.count() == 0 and book.every() == ()
    book.delete(["x"])
    assert book.next_id("season") == "season-1"
    assert not book.path.exists()  # the trainer's data folder is not written to


def test_a_new_id_is_the_next_free_in_the_whole_file(tmp_path):
    """Ids come from the scope, not the description, which may be empty and may change."""
    book = RequestDb(tmp_path / "r.sqlite")
    book.put((request("s1-1"), request("s1-3"), request("s1w2-1"), request("season-1")))
    assert book.next_id("s1") == "s1-2"  # a gap left by a deletion is reused
    assert book.next_id("s1w2") == "s1w2-2"
    assert book.next_id("s10") == "s10-1"  # s1's ids are not s10's
    assert book.next_id("jun08") == "jun08-1"


def test_scopes_around_a_date(dataset):
    assert dataset.scope(DAY) == day(dataset.target)
    assert dataset.scope(WEEK) == Scope(WEEK, date(2026, 9, 13), date(2026, 9, 19))
    assert dataset.scope(SESSION) == Scope(SESSION, date(2026, 9, 13), date(2026, 9, 26))
    assert dataset.scope(SEASON) == SEASON_2026
    labels = [describe(dataset.scope(k)) for k in (DAY, WEEK, SESSION, SEASON)]
    assert labels == [
        "Day: Wed Sep 16",
        "Week: Sep 13 to Sep 19",
        "Session: Sep 13 to Sep 26",
        "Season: 2026",
    ]
    prefixes = [id_prefix(dataset.scope(k), dataset) for k in (DAY, WEEK, SESSION, SEASON)]
    assert prefixes == ["sep16", "s1w1", "s1", "season"]


def test_an_unscoped_request_is_this_sessions_or_a_generated_one_this_days(dataset):
    assert scope_for(request("x", None), dataset) == dataset.scope(SESSION)
    generated = request("offering:x", None, tags=("clinic_import",))
    assert scope_for(generated, dataset) == dataset.scope(DAY)
    assert scope_for(request("y", SEASON_2026), dataset) == SEASON_2026


def test_a_hard_request_is_kept_at_weight_one(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.put((request("x", priority=Priority.MUST_HAPPEN, weight=3.0),))
    assert book.every()[0].weight == 1.0


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("priority", "STABILITY", "STABILITY is the solver's own"),
        ("scope", "fortnight", "no scope 'fortnight'"),
        ("first", "someday", "a date that is not a date"),
    ],
)
def test_a_row_the_app_could_not_have_written_is_refused(tmp_path, column, value, message):
    book = RequestDb(tmp_path / "r.sqlite")
    book.put((request("x"),))
    with sqlite3.connect(book.path) as db:
        db.execute(f'UPDATE requests SET "{column}" = ?', (value,))
    with pytest.raises(LoadError, match=message):
        book.every()


def test_a_file_from_another_version_is_refused(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema', '1');"
            "CREATE TABLE requests (home TEXT, position INTEGER, id TEXT);"
        )
    with pytest.raises(LoadError, match="earlier version .*format 1.*cannot read"):
        RequestDb(path).read(date(2026, 9, 16))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE meta SET value = '3'")
    with pytest.raises(LoadError, match="newer version .*Update Puppet Strings"):
        RequestDb(path).read(date(2026, 9, 16))


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no mode bits to speak of")
def test_the_file_is_the_puppet_masters_alone(tmp_path):
    book = RequestDb(tmp_path / "r.sqlite")
    book.put((request("x"),))
    assert os.stat(book.path).st_mode & 0o777 == 0o600


def test_export_and_import_hand_the_requests_over(book, tmp_path):
    handed = tmp_path / "handed.sqlite"
    assert book.export(handed) == 31
    theirs = RequestDb(tmp_path / "theirs.sqlite")
    theirs.put((request("mine"),))
    count, kept = theirs.import_file(handed)
    assert count == 31 and theirs.every() == book.every()
    assert kept == tmp_path / "theirs.before-import.sqlite"
    assert [r.id for r in RequestDb(kept).every()] == ["mine"]  # what was replaced is kept


def test_an_import_into_a_computer_with_no_requests_keeps_nothing(book, tmp_path):
    fresh = RequestDb(tmp_path / "fresh.sqlite")
    assert fresh.import_file(book.path) == (31, None)


def test_an_import_is_rewritten_from_the_version_it_was_written_in(book, tmp_path, dataset):
    """A role after WITH is theirs from syntax 6, so a file from 7 keeps it where it is."""
    handed = tmp_path / "handed.sqlite"
    book.export(handed)
    role = "REQUEST staff.dylan DO activities.clinics.riflery WITH staff.rob AS_ROLE roles.first"
    pick = "REQUEST staff.dylan DO 'x' DURING AT_LEAST 1 blocks.all"
    with sqlite3.connect(handed) as db:
        db.execute("UPDATE requests SET skedge = ? WHERE id = 'breaks'", (role,))
        db.execute("UPDATE requests SET skedge = ? WHERE id = 'dylan-off-ropes'", (pick,))
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('syntax', '7')")
    fresh = RequestDb(tmp_path / "fresh.sqlite")
    fresh.import_file(handed)
    assert fresh.upgrade(dataset)
    by_id = {r.id: r.skedge for r in fresh.every()}
    assert by_id["breaks"] == role
    assert by_id["dylan-off-ropes"] == "REQUEST staff.dylan DO 'x' DURING ANY 1 blocks.all"


@pytest.mark.parametrize("problem", ["not a database", "no meta", "older format", "bad row"])
def test_an_import_that_would_not_load_changes_nothing(book, tmp_path, problem):
    file = tmp_path / "file.sqlite"
    if problem == "not a database":
        file.write_text("id,description\n")
    else:
        book.export(file)
        with sqlite3.connect(file) as db:
            if problem == "no meta":
                db.execute("DROP TABLE meta")
            elif problem == "older format":
                db.execute("UPDATE meta SET value = '1'")
            else:
                db.execute("UPDATE requests SET weight = -1 WHERE id = 'breaks'")
    mine = RequestDb(tmp_path / "mine.sqlite")
    mine.put((request("mine"),))
    with pytest.raises(LoadError):
        mine.import_file(file)
    assert [r.id for r in mine.every()] == ["mine"]
    assert not (tmp_path / "mine.before-import.sqlite").exists()


def test_a_request_saved_in_the_app_is_in_the_file(fixtures_copy):
    from dataclasses import replace

    from puppet_strings.app.store import RequestStore
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, TARGET, saved_requests

    store = RequestStore(CsvSource(fixtures_copy), CONFIG)
    store.load(TARGET)
    saved = store.save(replace(request("", None), description="new"), None)
    assert saved.id == "s1-1" and saved.scope == store.dataset.scope(SESSION)
    assert saved_requests(fixtures_copy)["s1-1"].description == "new"
    store.delete("s1-1")
    assert "s1-1" not in saved_requests(fixtures_copy)


def test_one_days_offerings_are_not_another_days(fixtures_copy):
    """Imported clinics are scoped to the day, so the next day's load does not read them."""
    from puppet_strings.app.store import RequestStore
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, TARGET

    store = RequestStore(CsvSource(fixtures_copy), CONFIG)
    store.load(TARGET)
    assert store.offerings_loaded
    store.load(date(2026, 9, 17))  # which imports that day's own
    imported = [r.id for r in store.requests if "clinic_import" in r.tags]
    assert store.imported == len(imported) > 0
    assert all(i.startswith("offering:2026-09-17:") for i in imported)
    store.load(TARGET)
    assert store.imported == 0  # already imported
    ids = {r.id for r in store.requests if "clinic_import" in r.tags}
    assert ids and all(i.startswith("offering:2026-09-16:") for i in ids)


def test_the_old_generated_tag_is_renamed_on_open(fixtures_copy):
    """A file from before the rename would otherwise import every day's clinics again."""
    with sqlite3.connect(fixtures_copy / FIXTURE_FILE) as db:
        db.execute("UPDATE requests SET tags = 'generated, pin' WHERE tags = 'clinic_import'")
    requests = RequestDb(fixtures_copy / FIXTURE_FILE).every()
    imported = [r for r in requests if r.id.startswith("offering:")]
    assert imported and all(r.tags == ("clinic_import", "pin") for r in imported)
    assert not [r for r in requests if "generated" in r.tags]


def test_old_nested_date_names_are_rewritten_on_open(fixtures_copy):
    """A request written before `dates.session.one` became `dates.session_1` still loads."""
    old = "REQUEST staff.dylan DO 'x' ON {dates.session.one.week.two.all + dates.other.camp.all}"
    with sqlite3.connect(fixtures_copy / FIXTURE_FILE) as db:
        db.execute("UPDATE requests SET skedge = ? WHERE rowid = 1", (old,))
    (renamed,) = [
        r.skedge
        for r in RequestDb(fixtures_copy / FIXTURE_FILE).every()
        if "dates.camp" in r.skedge
    ]
    assert renamed == "REQUEST staff.dylan DO 'x' ON {dates.session_1.week_2.all + dates.camp.all}"


def test_date_names_in_words_are_rewritten_in_digits_on_open(fixtures_copy):
    """A request written before `dates.session_one` became `dates.session_1` still loads."""
    old = "REQUEST staff.dylan DO 'x' ON {dates.session_twelve.week_two.all + dates.camp.all}"
    with sqlite3.connect(fixtures_copy / FIXTURE_FILE) as db:
        db.execute("UPDATE requests SET skedge = ? WHERE rowid = 1", (old,))
    (renamed,) = [
        r.skedge
        for r in RequestDb(fixtures_copy / FIXTURE_FILE).every()
        if "dates.camp" in r.skedge
    ]
    assert renamed == "REQUEST staff.dylan DO 'x' ON {dates.session_12.week_2.all + dates.camp.all}"


def test_requests_written_in_an_older_skedge_are_rewritten_once(fixtures_copy, dataset):
    """A set matched right of NOT takes ANY now; a file from before is rewritten on its load."""
    old = "REQUEST staff.dylan NOT DO activities.clinics.ropes DURING blocks.all_clinics"
    with sqlite3.connect(fixtures_copy / FIXTURE_FILE) as db:
        db.execute("UPDATE requests SET skedge = ? WHERE id = 'dylan-off-ropes'", (old,))
        db.execute("DELETE FROM meta WHERE key = 'syntax'")
    book = RequestDb(fixtures_copy / FIXTURE_FILE)
    assert book.upgrade(dataset)
    (rewritten,) = [r.skedge for r in book.every() if r.id == "dylan-off-ropes"]
    assert rewritten == (
        "REQUEST staff.dylan NOT DO ANY activities.clinics.ropes DURING ANY blocks.all_clinics"
    )
    with sqlite3.connect(fixtures_copy / FIXTURE_FILE) as db:
        db.execute("UPDATE requests SET skedge = ? WHERE id = 'dylan-off-ropes'", (old,))
    assert not book.upgrade(dataset)  # once: the file says it is done
