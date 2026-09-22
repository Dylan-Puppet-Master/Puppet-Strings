"""Headless checks of the desktop app: models, filters, editor validation, and solving."""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from puppet_strings.app import palette  # noqa: E402
from puppet_strings.app.calendar_pane import ROWS  # noqa: E402
from puppet_strings.app.groups import ALL, DEFAULT_GROUPS, UNGROUPED  # noqa: E402
from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.model import Rest  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from tests.conftest import FIXTURES  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


OPEN_WINDOWS = []  # a window collected mid-solve would be destroyed off the main thread


def make_window(path, loaded=True):
    """A window on a copy of the fixtures, kept alive for the run."""
    window = MainWindow(RequestStore(CsvSource(path), Config(time_limit_seconds=10)))
    OPEN_WINDOWS.append(window)
    window.date_edit.setDate(QDate(2026, 9, 16))
    if loaded:
        window.reload()
        window.wait_for_load()
    return window


@pytest.fixture
def window(app, fixtures_copy):
    return make_window(fixtures_copy)


def visible_ids(window):
    return {window.proxy.data(window.proxy.index(r, 0)) for r in range(window.proxy.rowCount())}


def test_table_and_filters(window):
    assert window.proxy.rowCount() == 31
    window.tag_filter.setCurrentText("generated")
    assert window.proxy.rowCount() == 24
    window.tag_filter.setCurrentText("legal")
    assert visible_ids(window) == {"counselor-hours", "breaks"}
    window.tag_filter.setCurrentIndex(0)
    window.text_filter.setText("counselor hour")
    assert visible_ids(window) == {"counselor-hours"}
    window.text_filter.setText("")
    window.priority_filter.setCurrentText("MUST_HAPPEN")
    assert window.proxy.rowCount() == 3
    window.priority_filter.setCurrentIndex(0)
    window.staff_filter.setCurrentText("dylan")
    ids = visible_ids(window)
    assert "breaks" not in ids and {"dylan-off-ropes", "counselor-hours"} <= ids
    window.staff_filter.setCurrentIndex(0)
    window.activity_filter.setCurrentText("riflery")
    assert visible_ids(window) == {
        "clinic-preference",
        "clinic-variety",
        "offering:2026-09-16:riflery:clinic_3",
    }
    window.activity_filter.setCurrentIndex(0)
    window.date_check.setChecked(True)
    window.date_filter.setDate(QDate(2026, 9, 19))
    ids = visible_ids(window)
    assert "dylan-off-ropes" not in ids and "breaks" in ids


def test_editor_validation_and_save(window):
    editor = window.editor
    editor.clear()
    editor.description_edit.setText("Dylan's day off")
    editor.skedge_edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.nope")
    assert not editor.validate()
    assert "unknown name 'blocks.nope'" in editor.status.text()
    editor.skedge_edit.setPlainText("REQUEST EACH_OF staff.counselor DO 'x' DURING blocks.clinic_1")
    assert editor.validate()
    assert "3 EACH_OF copies" in editor.status.text()
    editor.tags_edit.setText("training, week 2")
    editor.save_button.click()
    assert window.model.rowCount() == 32
    assert editor.id_label.text() == "s1-1"  # numbered on its tab, not made of the wording
    saved = window.store.source.read("requests", "S1 Special")  # a new request is this span's
    row = next(r for r in saved if r[0] == "s1-1")
    assert row[saved[0].index("tags")] == "training, week 2"
    assert "week 2" in window.store.tags
    editor.description_edit.setText("Dylan's day off, changed")
    editor.save_button.click()
    assert editor.id_label.text() == "s1-1"  # rewording it keeps the id
    assert window.model.rowCount() == 32
    editor.clear()
    editor.skedge_edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    editor.validate()  # the editor validates 300 ms after typing; tests cannot wait
    editor.save_button.click()
    assert editor.id_label.text() == "s1-2"  # and a description is not needed at all
    assert window.model.request("s1-2").description == ""
    editor.delete_button.click()
    assert window.model.rowCount() == 32
    window._deleted("s1-1")
    assert window.model.rowCount() == 31


def test_selecting_a_row_fills_the_editor(window):
    index = window.proxy.index(0, 0)
    window.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectCurrent)
    assert window.editor.id_label.text() == window.proxy.data(index)


def resting_label(rest):
    """The dialog's own wording for a rest, so renaming a label cannot break these tests."""
    from puppet_strings.app.same_day import RESTING_CHOICES

    return next(text for text, choice in RESTING_CHOICES.items() if choice is rest)


def completions(editor):
    model = editor.skedge_edit.completer.completionModel()
    return [model.index(i, 0).data() for i in range(model.rowCount())]


def test_completer_opens_after_a_namespace_and_a_dot(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "REQUEST staff.")
    assert editor.skedge_edit.completer.completionPrefix() == "staff."
    assert "staff.dylan" in completions(editor) and "staff.counselor" in completions(editor)
    assert "activities.clinics.riflery" not in completions(editor)


def test_completer_finds_a_name_without_its_namespace(window):
    """Nobody thinks of Dylan as `staff.dylan`, so typing `dylan` is enough to find him."""
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "REQUEST dyl")
    assert completions(editor) == ["staff.dylan"]
    editor.skedge_edit.completer.activated.emit("staff.dylan")
    assert editor.skedge_edit.toPlainText() == "REQUEST staff.dylan"
    editor.skedge_edit.setPlainText("")
    QTest.keyClicks(editor.skedge_edit, "DURING clinic_3")
    assert completions(editor) == ["blocks.clinic_3"]
    editor.skedge_edit.setPlainText("")
    QTest.keyClicks(editor.skedge_edit, "AS_ROLE seco")
    assert completions(editor) == ["roles.second"]


def test_a_bare_word_never_suggests_a_date(window):
    """A date is written as a date or picked off the calendar; the season would bury a name."""
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "ON mond")
    assert completions(editor) == []
    QTest.keyClicks(editor.skedge_edit, "ay")
    assert not editor.skedge_edit.completer.popup().isVisible()
    editor.skedge_edit.setPlainText("")
    QTest.keyClicks(editor.skedge_edit, "ON dates.session.one.mond")
    assert completions(editor) == ["dates.session.one.mondays"]


def test_a_keyword_being_typed_is_not_a_name_being_looked_up(window):
    """`do` is a word on its way to being written, not a search for every name with do in it."""
    editor = window.editor
    editor.clear()
    for text in ("REQUEST staff.dylan do", "REQUEST staff.dylan DO 'x' during", "prefer"):
        editor.skedge_edit.setPlainText("")
        QTest.keyClicks(editor.skedge_edit, text)
        assert not editor.skedge_edit.completer.popup().isVisible(), text


def test_completer_narrows_as_the_name_is_typed(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "DURING blocks.cl")
    assert completions(editor) == [
        "blocks.clinic_1",
        "blocks.clinic_2",
        "blocks.clinic_3",
        "blocks.clinic_4",
    ]
    QTest.keyClicks(editor.skedge_edit, "inic_3")
    assert completions(editor) == ["blocks.clinic_3"]
    QTest.keyClicks(editor.skedge_edit, "9")
    assert completions(editor) == []
    assert not editor.skedge_edit.completer.popup().isVisible()


def test_choosing_a_completion_replaces_what_was_typed(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "ON dates.session.one.week.two.thu")
    assert "dates.session.one.week.two.thursday" in completions(editor)
    editor.skedge_edit.completer.activated.emit("dates.session.one.week.two.thursday")
    assert editor.skedge_edit.toPlainText() == "ON dates.session.one.week.two.thursday"


def test_completer_stays_shut_for_plain_words_and_dates(window):
    editor = window.editor
    editor.clear()
    for text in ("REQUEST ", "ON 2026-09-16", "NOT DO 'break'"):
        editor.skedge_edit.setPlainText("")
        QTest.keyClicks(editor.skedge_edit, text)
        assert not editor.skedge_edit.completer.popup().isVisible(), text


def test_completer_follows_the_loaded_dataset(app, tmp_path):
    copy = tmp_path / "other"
    shutil.copytree(FIXTURES, copy)
    window = make_window(copy, loaded=False)
    assert window.editor.skedge_edit.completer.completionModel().rowCount() == 0
    window.reload()
    window.wait_for_load()
    QTest.keyClicks(window.editor.skedge_edit, "REQUEST staff.cam")
    assert completions(window.editor) == ["staff.cam_vl"]


def test_namespaces_panel_lists_namespaces(window):
    names = window.names
    assert [names.topLevelItem(i).text(0) for i in range(names.topLevelItemCount())] == [
        "staff",
        "activities",
        "blocks",
        "dates",
        "roles",
        "metrics",
    ]
    assert names.topLevelItem(3).child(0).text(0).startswith("dates.")
    staff = names.topLevelItem(0)
    assert any(staff.child(i).text(0) == "staff.cam_vl" for i in range(staff.childCount()))
    names.picked.emit("staff.dylan")
    assert window.editor.skedge_edit.toPlainText().endswith("staff.dylan")


def child(item, text):
    return next(item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == text)


def test_namespaces_panel_nests_dotted_names(window):
    dates = next(
        window.names.topLevelItem(i)
        for i in range(window.names.topLevelItemCount())
        if window.names.topLevelItem(i).text(0) == "dates"
    )
    session = child(dates, "dates.session")
    assert session.data(0, Qt.UserRole) is None  # only a step on the way to a name
    one = child(session, "dates.session.one")
    assert one.data(0, Qt.UserRole) is None  # nor is a span: its dates are `.all`
    every = child(one, "dates.session.one.all")
    assert every.data(0, Qt.UserRole) == "dates.session.one.all" and every.text(1) == "14 dates"
    week = child(child(one, "dates.session.one.week"), "dates.session.one.week.two")
    monday = child(week, "dates.session.one.week.two.monday")
    assert monday.text(1) == "2026-09-21 (Monday)"
    window.editor.clear()
    window.names.setCurrentItem(session)  # not a name: nothing is inserted
    window.names._pick_current()
    assert window.editor.skedge_edit.toPlainText() == ""
    window.names.setCurrentItem(monday)
    window.names._pick_current()
    assert window.editor.skedge_edit.toPlainText() == "dates.session.one.week.two.monday"


def test_calendar_click_inserts_a_date(window):
    window.editor.clear()
    window.editor.skedge_edit.setPlainText("ON ")
    window.editor.skedge_edit.moveCursor(QTextCursor.End)
    window.calendar.clicked.emit(QDate(2026, 9, 18))
    assert window.editor.skedge_edit.toPlainText() == "ON 2026-09-18"
    assert window.calendar.minimumDate() < QDate(2000, 1, 1)  # any date can be picked
    assert (
        window.calendar.dateTextFormat(QDate(2026, 9, 13)).background().color().name()
        == palette.CAMP_DAY
    )
    assert window.calendar.dateTextFormat(QDate(2026, 10, 30)).background().style() == Qt.NoBrush
    window.calendar.clicked.emit(QDate(2026, 10, 2))
    assert window.editor.skedge_edit.toPlainText().endswith("2026-10-02")


def test_load_offerings_mirrors_the_offerings_tab(window):
    from dataclasses import replace

    before = window.model.rowCount()
    window.load_offerings()
    window.wait_for_offerings()
    assert window.model.rowCount() == before
    assert "Loaded 24 offerings" in window.status_label.text()
    # a clinic removed from the Offerings tab disappears on the next load
    trimmed = [o for o in window.store.dataset.offerings if o.activity != "riflery"]
    window.store.dataset = replace(window.store.dataset, offerings=tuple(trimmed))
    window.load_offerings()
    window.wait_for_offerings()
    assert window.model.rowCount() == before - 1
    assert not [r for r in window.store.requests if "riflery" in r.id]
    generated = [r for r in window.store.requests if "generated" in r.tags]
    assert len(generated) == 23 and all(r.priority.value == "CLINIC" for r in generated)


def test_reload_picks_up_a_row_deleted_on_the_sheet(window):
    import csv

    path = window.store.source.root / "requests" / "Season Requests.csv"
    index = window.proxy.index(0, 0)
    window.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectCurrent)
    shown = window.editor.original_id
    with path.open(newline="") as f:
        rows = [r for r in csv.reader(f) if r[0] != shown]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    window.reload()
    window.reload()  # a second click while loading queues another load, not a no-op
    window.wait_for_load()
    assert window.model.rowCount() == 30
    assert window.model.request(shown) is None
    assert window.editor.original_id is None and window.loader is None


def test_solve_uses_requests_saved_since_the_last_reload(app, tmp_path):
    import csv

    copy = tmp_path / "fresh"
    shutil.copytree(FIXTURES, copy)
    path = copy / "requests" / "S1 Clinics.csv"
    with path.open(newline="") as f:
        rows = [r for r in csv.reader(f) if "generated" not in r]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    window = make_window(copy)
    assert not window.store.offerings_loaded
    window.load_offerings()  # no Reload in between
    window.wait_for_offerings()
    assert window.store.offerings_loaded
    results = []
    window.run_solve()
    window.worker.done.disconnect()
    window.worker.done.connect(results.append)
    window.worker.wait(60000)
    app.processEvents()
    clinics = [a for a in results[0].assignments if a.activity in window.store.dataset.activities]
    assert clinics and results[0].unsatisfied


def test_solve_worker_produces_a_result(window, app):
    results = []
    window.run_solve()
    window.worker.done.disconnect()
    window.worker.done.connect(results.append)
    window.worker.wait(60000)
    app.processEvents()
    assert results and results[0].feasible


def test_same_day_is_offered_only_for_a_published_day(window, tmp_path):
    assert not window.same_day_action.isEnabled()
    assert not window.sleep_action.isVisible() and not window.sickness_action.isVisible()
    assert "not published" in window.status_label.text()

    from puppet_strings.publish.writer import publish
    from puppet_strings.solver.solve import solve

    publish(
        window.store.source,
        window.store.config,
        window.store.dataset,
        solve(window.store.current, window.store.config),
    )
    window.reload()
    window.wait_for_load()
    assert window.same_day_action.isEnabled() and "is published" in window.status_label.text()
    window.same_day_action.setChecked(True)
    assert window.same_day
    assert window.sleep_action.isVisible() and window.sickness_action.isVisible()


def test_the_sleep_and_sickness_dialogs_write_one_row_each(window):
    from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog

    sleep = SameDayDialog(window.store, SLEEP, window)
    assert sleep.penalty_box.value() == 1  # the agreement costs one RAL
    sleep.staff_box.setCurrentText("Vic")
    sleep.note_edit.setText("short sleep")
    sleep.apply_button.click()
    assert sleep.changed and sleep.table.rowCount() == 1
    assert [sleep.table.item(0, c).text() for c in range(3)] == ["Vic", "down 1 RAL", "short sleep"]

    sickness = SameDayDialog(window.store, SICKNESS, window)
    sickness.staff_box.setCurrentText("Alesa")
    sickness.resting_box.setCurrentText(resting_label(Rest.MORNING))
    sickness.apply_button.click()
    assert sickness.table.rowCount() == 2

    written = window.store.source.read("config", "Adjustments")
    assert written[0] == ["date", "staff", "resting", "RAL_penalty", "note"]
    assert ["2026-09-16", "Alesa", "morning", "", ""] in written
    assert ["2026-09-16", "Vic", "", "1", "short sleep"] in written

    # reloading applies it: Vic is a RAL lower, Alesa is off for the morning blocks only
    window.reload()
    window.wait_for_load()
    assert window.store.dataset.staff["vic"].ral == 4
    alesa = window.store.dataset.staff["alesa"]
    assert alesa.resting_blocks == {
        "breakfast",
        "clinic_1",
        "clinic_2",
    }  # the morning, by block start
    assert "alesa" in window.store.dataset.staff_categories["all"]  # she works the afternoon

    sickness = SameDayDialog(window.store, SICKNESS, window)
    sickness.staff_box.setCurrentText("Vic")
    sickness.remove_button.click()
    assert [row[1] for row in window.store.source.read("config", "Adjustments")[1:]] == ["Alesa"]


def test_one_person_can_be_both_short_of_sleep_and_resting(window):
    from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog

    sleep = SameDayDialog(window.store, SLEEP, window)
    sleep.staff_box.setCurrentText("Vic")
    sleep.apply_button.click()
    sickness = SameDayDialog(window.store, SICKNESS, window)
    sickness.staff_box.setCurrentText("Vic")
    sickness.resting_box.setCurrentText(resting_label(Rest.AFTERNOON))
    sickness.apply_button.click()
    (row,) = window.store.dataset.today_adjustments
    assert row.ral_penalty == 1 and row.summary == "resting this afternoon and down 1 RAL"
    assert len(window.store.source.read("config", "Adjustments")) == 2  # one header, one row


def test_the_solvers_own_priority_is_not_offered(window):
    from puppet_strings.model import Priority

    offered = [
        window.editor.priority_box.itemText(i) for i in range(window.editor.priority_box.count())
    ]
    assert Priority.STABILITY.value not in offered
    assert offered == ["MUST_HAPPEN", "CLINIC", "HIGH", "MEDIUM", "LOW"]
    filters = [window.priority_filter.itemText(i) for i in range(window.priority_filter.count())]
    assert Priority.STABILITY.value not in filters


def test_solving_puts_a_modal_panel_up_and_takes_it_down(window, app):
    from puppet_strings.app.busy import BusyDialog

    window.run_solve()
    busy = window.busy
    assert isinstance(busy, BusyDialog) and busy.isVisible()
    assert busy.windowModality() == Qt.ApplicationModal  # the window behind takes no clicks
    assert busy.bar.minimum() == busy.bar.maximum() == 0  # a sweep, not a percentage
    window.worker.done.disconnect()  # keep the schedule dialog shut
    window.worker.wait(60000)
    app.processEvents()
    assert window.busy is None and not busy.isVisible()


def test_cancelling_the_panel_asks_the_solve_to_stop(window, app):
    window.run_solve()
    worker = window.worker
    worker.done.disconnect()
    assert not worker.cancel.stopped
    window.busy.cancel_button.click()
    assert worker.cancel.stopped
    assert not window.busy.cancel_button.isEnabled()  # asking twice does nothing
    worker.wait(60000)
    app.processEvents()
    assert window.busy is None


def test_the_busy_panel_asks_to_stop_once(app):
    from puppet_strings.app.busy import STOPPING, BusyDialog

    dialog = BusyDialog("Solving…")
    asked = []
    dialog.cancelled.connect(lambda: asked.append(1))
    dialog.cancel_button.click()
    assert asked == [1] and dialog.label.text() == STOPPING
    dialog.reject()  # Escape after asking leaves the work alone
    assert asked == [1]


# -- groups -------------------------------------------------------------------------------


def group_rows(window):
    """What the groups pane shows, as {group: count}."""
    pane = window.groups.list
    return {
        pane.item(r).data(Qt.UserRole): int(pane.item(r).text().rsplit("(", 1)[1].rstrip(")"))
        for r in range(pane.count())
    }


def pick_group(window, name):
    window.groups.list.setCurrentRow(window.groups._row_of(name))


def test_groups_pane_lists_defaults_with_counts(window):
    rows = group_rows(window)
    assert list(rows)[:2] == [ALL, UNGROUPED]
    assert list(rows)[2:] == list(DEFAULT_GROUPS)
    assert rows[ALL] == 31
    assert rows[UNGROUPED] == 25  # the generated clinic requests are in no group
    assert rows["Special daily requests"] == 3 and rows["Special weekly requests"] == 3


def test_picking_a_group_filters_the_table(window):
    pick_group(window, "Special weekly requests")
    assert visible_ids(window) == {"clinic-preference", "clinic-variety", "dylan-off-ropes"}
    assert "3 requests in Special weekly requests" in window.status_label.text()
    window.priority_filter.setCurrentText("MEDIUM")  # filters narrow within the group
    assert visible_ids(window) == {"clinic-preference", "clinic-variety"}
    window.priority_filter.setCurrentIndex(0)
    pick_group(window, UNGROUPED)
    shown = visible_ids(window)
    assert len(shown) == 25 and all("offering" in i or i == "cabin-acts" for i in shown)
    pick_group(window, ALL)
    assert window.proxy.rowCount() == 31


def test_making_a_group_and_dragging_requests_onto_it(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Ropes rewrite", True))
    window.groups.new_group()
    assert group_rows(window)["Ropes rewrite"] == 0  # an empty group stays in the pane
    assert window.groups.current == "Ropes rewrite" and visible_ids(window) == set()
    window.groups.dropped.emit(["dylan-off-ropes", "breaks"], "Ropes rewrite")
    assert group_rows(window)["Ropes rewrite"] == 2
    assert visible_ids(window) == {"dylan-off-ropes", "breaks"}
    saved = window.store.source.read("requests", "Season Requests")
    row = next(r for r in saved if r[0] == "dylan-off-ropes")
    assert row[saved[0].index("group")] == "Ropes rewrite"  # one group, the one it moved to
    assert group_rows(window)["Special weekly requests"] == 2  # it left the shelf it was on
    window.groups.dropped.emit(["breaks"], UNGROUPED)  # dragged off every shelf
    assert group_rows(window)["Ropes rewrite"] == 1
    assert next(r for r in window.store.requests if r.id == "breaks").group == ""


def test_renaming_and_deleting_a_group(window, monkeypatch):
    names = iter([("Ropes rewrite", True), ("Ropes", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(names))
    window.groups.new_group()
    window.groups.dropped.emit(["dylan-off-ropes", "breaks"], "Ropes rewrite")
    window.groups.rename_group()
    assert "Ropes rewrite" not in group_rows(window)
    assert group_rows(window)["Ropes"] == 2 and window.groups.current == "Ropes"
    assert {r.id for r in window.store.requests if r.group == "Ropes"} == {
        "dylan-off-ropes",
        "breaks",
    }
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.groups.delete_group()
    assert "Ropes" not in group_rows(window)
    assert window.model.rowCount() == 31  # the requests stay, on no shelf
    assert group_rows(window)[UNGROUPED] == 27


def test_a_default_group_cannot_be_renamed_and_a_name_is_not_taken_twice(window, monkeypatch):
    pick_group(window, "Special daily requests")
    assert not window.groups.rename_button.isEnabled()
    assert not window.groups.delete_button.isEnabled()
    pick_group(window, ALL)
    assert not window.groups.rename_button.isEnabled()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("  special   DAILY requests ", True)
    )
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda _w, _t, text: told.append(text))
    window.groups.new_group()
    assert told and "already a group" in told[0]
    assert len(group_rows(window)) == 4  # nothing added


def test_the_editor_shows_a_group_but_does_not_choose_one(window):
    """The pane is where a request's group is decided, so the editor only reports it."""
    editor = window.editor
    editor.show_request(window.model.request("dylan-off-ropes"))
    assert editor.group_label.text() == "Special weekly requests"
    assert editor.current().group == "Special weekly requests"
    editor.save_button.click()
    assert group_rows(window)["Special weekly requests"] == 3  # saving does not move it
    assert not hasattr(editor, "groups_edit")


def test_a_new_request_joins_the_group_being_shown(window):
    pick_group(window, "Special weekly requests")
    window.new_request()
    assert window.editor.group_label.text() == "Special weekly requests"
    window.editor.skedge_edit.setPlainText("REQUEST staff.dylan FREE DURING blocks.clinic_1")
    window.editor.validate()
    window.editor.save_button.click()
    assert group_rows(window)["Special weekly requests"] == 4
    pick_group(window, ALL)
    window.new_request()
    assert window.editor.group_label.text().startswith("none")  # ALL is not a shelf


def test_a_group_can_say_which_tab_its_new_requests_go_to(window):
    window.store.group_tabs.set("Special weekly requests", "Season Requests")
    pick_group(window, "Special weekly requests")
    window.new_request()
    assert window.editor.home_box.currentText() == "Season Requests"
    pick_group(window, "Special daily requests")
    window.new_request()
    assert window.editor.home_box.currentText() == "S1 Special"  # nothing said: this span's
    window.store.group_tabs.set("Special weekly requests", "")


# -- the requester ------------------------------------------------------------------------


def test_requester_completes_and_is_checked(window):
    editor = window.editor
    editor.show_request(window.model.request("dylan-off-ropes"))
    assert editor.requester_edit.text() == "dylan"
    model = editor.requester_completer.model()
    assert "cam_vl" in model.stringList() and "dylan" in model.stringList()
    editor.requester_edit.setText("Mary Kate")
    assert editor.current().requester == "mary_kate"  # a typed name is normalized
    assert not editor.validate()
    assert "unknown requester 'mary_kate'" in editor.status.text()
    editor.requester_edit.setText("rob")
    assert editor.validate()
    editor.save_button.click()
    saved = window.store.source.read("requests", "Season Requests")
    row = next(r for r in saved if r[0] == "dylan-off-ropes")
    assert row[saved[0].index("requester")] == "rob"


# -- saving a request that is not about the date being scheduled ---------------------------


def write_request(window, skedge, description="Elsewhere"):
    editor = window.editor
    editor.clear()
    editor.description_edit.setText(description)
    editor.skedge_edit.setPlainText(skedge)
    editor.validate()
    return editor


def test_saving_a_request_outside_the_date_asks_first(window, monkeypatch):
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda _w, _t, text, *a: asked.append(text) or QMessageBox.Cancel
    )
    editor = write_request(
        window,
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL_OF dates.session.two.week.one.all",
    )
    editor.save_button.click()
    assert asked and "does not cover 2026-09-16" in asked[0]
    assert "2026-09-27, 2026-09-28, 2026-09-29 and 4 more" in asked[0]
    assert window.model.rowCount() == 31  # cancelled: nothing saved, still editing
    assert window.editor.original_id is None
    assert "Not saved" in window.status_label.text()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    editor.save_button.click()
    assert window.model.rowCount() == 32
    saved = editor.original_id
    assert window.model.request(saved) is not None
    window.date_check.setChecked(True)  # it does nothing on the date being scheduled
    window.date_filter.setDate(QDate(2026, 9, 16))
    assert saved not in visible_ids(window)
    window.date_filter.setDate(QDate(2026, 9, 28))
    assert saved in visible_ids(window)


def test_saving_a_request_about_this_date_asks_nothing(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: pytest.fail("should not have asked")
    )
    for skedge in (
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON dates.target",
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1",  # no ON: every day
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL_OF dates.session.one.week.one.all",
    ):
        editor = write_request(window, skedge, description=f"ok {skedge[-6:]}")
        editor.save_button.click()
        assert editor.original_id is not None


# -- the calendar --------------------------------------------------------------------------


def test_calendar_labels_weeks_with_their_session(window):
    calendar = window.calendar
    assert calendar.monthShown() == 9 and calendar.yearShown() == 2026
    labelled = {calendar.row_start(r).toString("yyyy-MM-dd"): calendar.week_of_row(r) for r in ROWS}
    assert labelled["2026-09-13"] == (1, 1)  # the week the target falls in
    assert labelled["2026-09-20"] == (1, 2)
    assert labelled["2026-09-27"] == (2, 1)
    assert labelled["2026-08-30"] == (None, None)  # before camp: no label
    calendar.setCurrentPage(2026, 10)
    assert calendar.week_of_row(1) == (2, 1)  # the week of 2026-10-03, camp's last day
    assert calendar.week_of_row(3) == (None, None)


def test_the_calendar_starts_its_weeks_where_camp_does(window):
    """Qt begins the week wherever the machine says; a row has to be one week of a span."""
    from PySide6.QtCore import Qt

    window.calendar.setFirstDayOfWeek(Qt.Monday)  # what a Monday-first locale hands it
    window.calendar.show_dataset(window.store.dataset)
    assert window.calendar.firstDayOfWeek() == Qt.Sunday  # session 1 starts Sunday 2026-09-13
    assert window.calendar.row_start(3).toString("yyyy-MM-dd") == "2026-09-13"


def test_the_calendar_is_numbered_even_when_the_load_fails(app, fixtures_copy, monkeypatch):
    """The Calendar sheet says which week of which session a date is; nothing else does."""
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    (fixtures_copy / "skills" / "Skills.csv").write_text("nonsense\n")
    window = make_window(fixtures_copy)
    assert window.store.dataset is None  # the load itself got nowhere
    assert window.calendar.week_of_row(3) == (1, 1)  # the week of 2026-09-16, all the same
    assert (
        window.calendar.dateTextFormat(QDate(2026, 9, 16)).background().color().name()
        == palette.CAMP_DAY
    )


# -- conflicts ------------------------------------------------------------------------------


PIN_RIFLERY = (
    "REQUEST staff.dylan DO activities.clinics.riflery DURING blocks.clinic_1 ON dates.target"
)
DYLAN_FREE = "REQUEST staff.dylan FREE DURING blocks.clinic_1 ON dates.target"


def save_request(window, description, skedge, priority="MUST_HAPPEN"):
    """Write a request in the editor and save it. Returns the id it was saved under."""
    editor = write_request(window, skedge, description)
    editor.priority_box.setCurrentText(priority)
    editor.validate()
    editor.save_button.click()
    return editor.original_id


def tree_rows(pane):
    """The pane as (heading, [child text]) pairs."""
    return [
        (
            pane.topLevelItem(i).text(0),
            [
                pane.topLevelItem(i).child(c).text(0)
                for c in range(pane.topLevelItem(i).childCount())
            ],
        )
        for i in range(pane.topLevelItemCount())
    ]


def test_the_conflicts_pane_starts_empty(window):
    assert window.conflicts.topLevelItemCount() == 0
    assert window.conflicts_dock.windowTitle() == "Conflicts"
    assert "No conflicts" in window.status_label.text()


def test_saving_a_contradiction_groups_it_in_the_pane(window):
    riflery = save_request(window, "Dylan on riflery", PIN_RIFLERY)
    assert window.conflicts.topLevelItemCount() == 0
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    assert "it conflicts with 1 other request(s)" in window.status_label.text()
    (heading, children) = tree_rows(window.conflicts)[0]
    assert heading == "dylan · Wed 2026-09-16 · clinic_1"
    assert children[:2] == [riflery, free]  # grouped under the collision
    assert window.conflicts_dock.windowTitle() == "Conflicts (1)"
    heading = window.conflicts.topLevelItem(0)
    assert heading.text(2) == "must be free, and is asked to do riflery"
    assert heading.childCount() == 2  # one reason, so it is said once, in the heading


def test_a_contradiction_the_solver_can_settle_is_not_a_conflict(window):
    """Only MUST_HAPPEN requests can make a day impossible, so only they are reported."""
    save_request(window, "Dylan on riflery", PIN_RIFLERY)
    save_request(window, "Dylan is free", DYLAN_FREE, priority="HIGH")
    assert window.conflicts.topLevelItemCount() == 0
    assert window.conflicts_dock.windowTitle() == "Conflicts"


def test_a_request_appears_under_every_collision_it_is_in(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)  # other dates
    wednesday = [
        save_request(window, "Dylan is free", DYLAN_FREE),
        save_request(window, "Dylan on riflery", PIN_RIFLERY),
    ]
    friday = [
        save_request(window, "Friday riflery", PIN_RIFLERY.replace("dates.target", "2026-09-18")),
        save_request(window, "Friday free", DYLAN_FREE.replace("dates.target", "2026-09-18")),
    ]
    rows = tree_rows(window.conflicts)
    assert [heading for heading, _ in rows] == [
        "dylan · Wed 2026-09-16 · clinic_1",
        "dylan · Fri 2026-09-18 · clinic_1",
    ]
    assert [sorted(c for c in children if c) for _, children in rows] == [
        sorted(wednesday),
        sorted(friday),
    ]


def test_deleting_a_request_clears_its_conflict(window):
    save_request(window, "Dylan on riflery", PIN_RIFLERY)
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    assert window.conflicts.topLevelItemCount() == 1
    window.editor.show_request(window.model.request(free))
    window.editor.delete_button.click()
    assert window.conflicts.topLevelItemCount() == 0
    assert window.conflicts_dock.windowTitle() == "Conflicts"


def conflict_child(window, request_id):
    """The row for one request under the first collision in the pane."""
    heading = window.conflicts.topLevelItem(0)
    rows = (heading.child(i) for i in range(heading.childCount()))
    return next(row for row in rows if row.text(0) == request_id)


def test_double_clicking_a_conflict_opens_that_request(window):
    riflery = save_request(window, "Dylan on riflery", PIN_RIFLERY)
    save_request(window, "Dylan is free", DYLAN_FREE)
    window.editor.clear()
    window.conflicts.itemDoubleClicked.emit(conflict_child(window, riflery), 0)
    assert window.editor.original_id == riflery
    heading = window.conflicts.topLevelItem(0)
    window.conflicts.itemDoubleClicked.emit(heading, 0)  # the heading is not a request
    assert window.editor.original_id == riflery


def test_a_conflicting_request_opens_even_when_the_group_hides_it(window):
    save_request(window, "Dylan on riflery", PIN_RIFLERY)
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    pick_group(window, "Special daily requests")
    assert free not in visible_ids(window)
    window.editor.clear()
    window.conflicts.itemDoubleClicked.emit(conflict_child(window, free), 0)
    assert window.editor.original_id == free


# -- saying what the window is doing ---------------------------------------------------------


def test_saving_says_so_and_then_says_it_is_done(window):
    editor = window.editor
    editor.clear()
    editor.description_edit.setText("Dylan's day off")
    editor.skedge_edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    assert editor.validate()
    assert editor.save_button.text() == "Save"
    editor.save_button.click()
    assert editor.save_button.text() == "Save"  # back to itself once the write is done
    assert editor.status.text().startswith("✓ Saved s1-1 at ")
    assert f"color: {palette.GOOD}" in editor.status.styleSheet()
    assert editor.save_button.isEnabled()
    editor.description_edit.setText("changed")  # editing clears the confirmation
    assert editor.validate() and editor.status.text() == "Valid"


def test_a_save_that_is_called_off_leaves_the_editor_alone(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    editor = write_request(
        window,
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL_OF dates.session.two.week.one.all",
    )
    editor.save_button.click()
    assert editor.save_button.text() == "Save" and editor.save_button.isEnabled()
    assert editor.status.text() == "Not saved; still editing"
    assert f"color: {palette.QUIET}" in editor.status.styleSheet()


def test_saving_shows_a_conflict_in_the_confirmation(window):
    save_request(window, "Dylan on riflery", PIN_RIFLERY)
    save_request(window, "Dylan is free", DYLAN_FREE)
    assert "it conflicts with 1 other request(s)" in window.editor.status.text()


def test_reloading_puts_up_a_panel_until_the_sheets_are_read(window):
    assert window.progress is None
    window.reload()
    assert window.progress is not None
    assert window.progress.label.text() == "Reading the sheets for 2026-09-16…"
    assert not window.progress.cancel_button.isVisible()  # reading cannot be called off
    window.wait_for_load()
    assert window.progress is None


def test_a_panel_that_cannot_be_cancelled_ignores_escape(window):
    window.reload()
    panel = window.progress
    panel.reject()  # Escape
    assert panel.label.text() != "Stopping…" and window.progress is panel
    window.wait_for_load()


def test_loading_offerings_puts_up_a_panel_and_keeps_the_window_painting(window):
    """The panel goes up before the work starts, and the work runs off the UI thread."""
    window.load_offerings()
    assert window.progress is not None  # up while the sheet is being written
    assert window.progress.label.text() == "Loading the offerings for 2026-09-16…"
    assert not window.progress.cancel_button.isVisible()
    window.wait_for_offerings()
    assert window.progress is None and window.offerings is None
    assert "Loaded 24 offerings" in window.status_label.text()


def test_a_second_click_while_the_offerings_load_does_nothing(window):
    window.load_offerings()
    first = window.offerings
    window.load_offerings()
    assert window.offerings is first
    window.wait_for_offerings()
    assert "Loaded 24 offerings" in window.status_label.text()


def test_an_offerings_load_that_fails_says_so(window, monkeypatch):
    from puppet_strings.sheets.source import LoadError

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _w, _t, text: shown.append(text))

    def refuse():
        raise LoadError("Offerings: no tab")

    monkeypatch.setattr(window.store, "load_offerings", refuse)
    window.load_offerings()
    window.wait_for_offerings()
    assert shown == ["Offerings: no tab"]
    assert window.progress is None


class FakeDialog:
    """Stands in for a popup: records what it was given and is closed at once."""

    def __init__(self, opened, value):
        opened.append(value)

    def exec(self):
        return 0


def test_double_clicking_a_name_opens_what_it_stands_for(window, monkeypatch):
    from puppet_strings.app import main as main_module

    shown = []
    monkeypatch.setattr(
        main_module, "DetailsDialog", lambda found, parent: FakeDialog(shown, found)
    )
    staff_top = next(
        window.names.topLevelItem(i)
        for i in range(window.names.topLevelItemCount())
        if window.names.topLevelItem(i).text(0) == "staff"
    )
    dylan = child(staff_top, "staff.dylan")
    window.names.itemDoubleClicked.emit(dylan, 0)
    assert shown and shown[0].subtitle == "Dylan, RAL 5"


def test_double_clicking_a_metric_opens_its_table(window, monkeypatch):
    from puppet_strings.app import main as main_module

    opened = []
    monkeypatch.setattr(
        main_module, "MetricDialog", lambda *args, **kwargs: FakeDialog(opened, args[2])
    )
    metrics = next(
        window.names.topLevelItem(i)
        for i in range(window.names.topLevelItemCount())
        if window.names.topLevelItem(i).text(0) == "metrics"
    )
    window.names.itemDoubleClicked.emit(child(metrics, "metrics.preference"), 0)
    assert opened == ["preference"]


def test_a_date_off_the_calendar_asks_for_another_one(window, monkeypatch):
    """Not a camp day is a warning naming a date to try, not a critical load failure."""
    warned, critical = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda _w, _t, text: warned.append(text))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: critical.append(a))
    window.date_edit.setDate(QDate(2026, 12, 25))
    window.reload()
    window.wait_for_load()
    assert warned and "2026-12-25 is not a camp day" in warned[0]
    assert "nearest camp day is 2026-10-03" in warned[0]
    assert not critical  # it is the date that is wrong, not the sheets
    assert "not a camp day" in window.status_label.text()
    assert window.progress is None
    # and picking a camp day loads as usual
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.reload()
    window.wait_for_load()
    assert "Loaded" in window.status_label.text()


def test_the_on_date_filter_follows_the_target_date(window):
    """It starts on the target and moves with it; moving it back leaves the target alone."""
    assert window.date_filter.date() == window.date_edit.date()
    window.date_edit.setDate(QDate(2026, 9, 18))
    assert window.date_filter.date() == QDate(2026, 9, 18)
    window.date_filter.setDate(QDate(2026, 9, 21))
    assert window.date_edit.date() == QDate(2026, 9, 18)  # the target did not move
    assert window.target.isoformat() == "2026-09-18"


def test_a_shaded_calendar_day_says_what_to_write_on_it(window):
    """A shaded cell with no text colour of its own is written in the palette's ink."""
    shading = window.calendar.dateTextFormat(QDate(2026, 9, 16))
    assert shading.background().color().name() == palette.CAMP_DAY
    assert shading.foreground().color().name() == palette.INK


def test_a_conflict_heading_says_what_to_write_on_it(app):
    """Same as the calendar: a shaded heading must carry its own text colour."""
    from datetime import date as _date

    from puppet_strings.app.conflicts import Conflict
    from puppet_strings.app.conflicts_panel import _group

    clash = Conflict("dylan", _date(2026, 9, 16), "clinic_1", ("both at once",), ("a", "b"))
    heading = _group(clash, {})
    for column in range(3):
        assert heading.background(column).color().name() == palette.CLASH
    assert heading.foreground(0).color().name() == palette.BAD
    assert heading.foreground(1).color().name() == palette.INK
    assert heading.foreground(2).color().name() == palette.INK


def test_every_shading_is_a_dark_one_that_ink_reads_on(app):
    """The window is dark, so a shading that drifts light would be white on near-white."""
    from PySide6.QtGui import QColor, QPalette

    ink = QColor(palette.INK).lightness()
    for shading in (
        palette.WINDOW,
        palette.SURFACE,
        palette.SUNKEN,
        palette.CAMP_DAY,
        palette.CLASH,
    ):
        assert QColor(shading).lightness() < ink / 2
    palette.apply(app)
    assert app.palette().color(QPalette.Window).lightness() < 128


def test_the_editor_keeps_a_request_on_its_own_tab(window):
    """The tab a request is on is when it applies, so editing one must not move it."""
    editor = window.editor
    editor.show_request(window.model.request("breaks"))
    assert editor.home_box.currentText() == "Season Requests"
    assert [editor.home_box.itemText(i) for i in range(editor.home_box.count())] == [
        "Season Requests",
        "S1 Clinics",
        "S1 Special",
    ]
    editor.save_button.click()
    season = window.store.source.read("requests", "Season Requests")
    assert any(row[0] == "breaks" for row in season)  # written back where it was
    editor.clear()
    assert editor.home_box.currentText() == "S1 Special"  # a new one is this session's


def coloured(edit, word: str) -> str:
    """The colour the highlighter paints one word of the Skedge box in."""
    text = edit.toPlainText()
    at = text.index(word)
    block = edit.document().findBlock(at)
    start = at - block.position()
    for run in block.layout().formats():
        if run.start <= start < run.start + run.length:
            return run.format.foreground().color().name()
    return ""


def test_a_keyword_is_coloured_in_whichever_case_it_is_written_in(window):
    """Skedge reads `request` and `REQUEST` alike, so the editor colours them alike."""
    edit = window.editor.skedge_edit
    edit.setPlainText("request staff.dylan do 'x' during blocks.clinic_1")
    assert coloured(edit, "request") == palette.KEYWORD
    assert coloured(edit, "during") == palette.KEYWORD
    assert coloured(edit, "staff.dylan") == palette.NAME
    edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    assert coloured(edit, "REQUEST") == palette.KEYWORD
