"""Headless checks of the desktop app: models, filters, editor validation, and solving."""

import os
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

import puppet_strings  # noqa: E402
from puppet_strings.app import palette  # noqa: E402
from puppet_strings.app.calendar_pane import ROWS  # noqa: E402
from puppet_strings.app.groups import ALL, DEFAULT_GROUPS, UNGROUPED  # noqa: E402
from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.model import Rest  # noqa: E402
from puppet_strings.sheets.source import CsvSource, LoadError  # noqa: E402
from tests.conftest import FIXTURES, delete_requests, family_camp, saved_requests  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


OPEN_WINDOWS = []  # a window collected mid-solve would be destroyed off the main thread


def make_window(path, loaded=True):
    """A window on a copy of the fixtures, kept alive for the run."""
    window = MainWindow(RequestStore(CsvSource(path), Config(tier_seconds_limit=10)))
    OPEN_WINDOWS.append(window)
    window.wait_for_calendar()
    window.date_edit.setDate(QDate(2026, 9, 16))
    if loaded:
        window.reload()
        window.wait_for_load()
    return window


@pytest.fixture
def window(app, fixtures_copy):
    return make_window(fixtures_copy)


@pytest.fixture(autouse=True)
def informed(monkeypatch):
    """What information popups said, recorded instead of shown: a real one waits for a click."""
    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda _w, _t, text, *a: said.append(text))
    return said


def test_nothing_but_the_calendar_is_read_until_reload(app, fixtures_copy):
    """The day wanted is often not the default one, so opening the window reads only the
    Calendar sheet, which is what the day is picked from."""
    window = make_window(fixtures_copy, loaded=False)
    assert window.loader is None and window.store.dataset is None
    assert window.status_label.text().strip() == "Pick a target date and press Reload."
    window.run_solve()
    assert window.worker is None  # nothing to solve against yet
    window.reload()
    window.wait_for_load()
    assert window.store.dataset.target == date(2026, 9, 16)


def test_a_folder_of_fixtures_is_not_backed_up_to_drive(window):
    """It carries its own requests and has no account to put a copy anywhere."""
    assert window.store.fixtures and window.backup is None


def visible_ids(window):
    return {window.proxy.data(window.proxy.index(r, 0)) for r in range(window.proxy.rowCount())}


def test_table_and_filters(window):
    assert window.proxy.rowCount() == 31
    window.tag_filter.setCurrentText("clinic_import")
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
    window.date_filter.setDate(QDate(2026, 9, 19))
    ids = visible_ids(window)
    assert "dylan-off-ropes" not in ids and "breaks" in ids


def test_a_target_session_name_can_be_saved_on_a_date_in_no_session(window):
    """It names no dates on this one, but is right on a session's, so Save stays on."""
    editor = window.editor
    editor.clear()
    editor.dataset = family_camp(editor.dataset)
    editor.skedge_edit.setPlainText(
        "REQUEST staff.dylan DO 'x' DURING ANY 1 blocks ON dates.session_target"
    )
    assert editor.validate() and editor.save_button.isEnabled()
    assert "which is not a session" in editor.status.text()


def test_editor_validation_and_save(window):
    editor = window.editor
    editor.clear()
    editor.description_edit.setText("Dylan's day off")
    editor.skedge_edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.nope")
    assert not editor.validate()
    assert "unknown name 'blocks.nope'" in editor.status.text()
    editor.skedge_edit.setPlainText("REQUEST EACH staff.counselor DO 'x' DURING blocks.clinic_1")
    assert editor.validate()
    assert "3 EACH copies" in editor.status.text()
    editor.tags_edit.setText("training, week 2")
    editor.save_button.click()
    assert window.model.rowCount() == 32
    assert editor.id_label.text() == "s1-1"  # numbered in its scope, not made of the wording
    saved = saved_requests(window.store.source.root)["s1-1"]
    assert saved.tags == ("training", "week 2")
    assert saved.scope == window.store.dataset.scope("session")  # a new one is this session's
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


def test_a_bare_word_suggests_a_date_name(window):
    """With no day names under every span, the dates are few enough to offer like the rest."""
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "ON mond")
    assert completions(editor) == ["dates.mondays"]
    editor.skedge_edit.setPlainText("")
    QTest.keyClicks(editor.skedge_edit, "ON weeke")
    assert completions(editor) == ["dates.weekends"]
    editor.skedge_edit.setPlainText("")
    QTest.keyClicks(editor.skedge_edit, "ON session_2")
    assert completions(editor) == ["dates.session_2", "dates.session_2.week_1"]


def test_moving_the_cursor_does_not_open_the_completer(window):
    """Arrowing through a name already written is not typing it."""
    editor = window.editor
    editor.clear()
    editor.skedge_edit.setPlainText("REQUEST staff.dy")
    editor.skedge_edit.moveCursor(QTextCursor.End)
    popup = editor.skedge_edit.completer.popup()
    QTest.keyClick(editor.skedge_edit, Qt.Key_Left)
    QTest.keyClick(editor.skedge_edit, Qt.Key_Right)
    assert not popup.isVisible()
    QTest.keyClicks(editor.skedge_edit, "l")
    assert popup.isVisible()
    QTest.keyClick(editor.skedge_edit, Qt.Key_Left)
    assert not popup.isVisible()


def test_ctrl_s_saves_with_the_completer_open(window):
    """The popup takes the keys while it is up; Ctrl+S must still save."""
    editor = window.editor
    editor.clear()
    editor.description_edit.setText("dylan free")
    QTest.keyClicks(editor.skedge_edit, "REQUEST staff.dyl")
    popup = editor.skedge_edit.completer.popup()
    assert popup.isVisible()
    editor.skedge_edit.setPlainText(DYLAN_FREE)
    editor.skedge_edit.moveCursor(QTextCursor.End)
    QTest.keyClicks(editor.skedge_edit, " # staff.dyl")  # a comment, so it still validates
    assert popup.isVisible()
    QTest.keyClick(popup, Qt.Key_S, Qt.ControlModifier)
    assert not popup.isVisible()
    assert editor.original_id and window.model.request(editor.original_id) is not None


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
    QTest.keyClicks(editor.skedge_edit, "ON dates.session_1.we")
    assert "dates.session_1.week_2" in completions(editor)
    editor.skedge_edit.completer.activated.emit("dates.session_1.week_2")
    assert editor.skedge_edit.toPlainText() == "ON dates.session_1.week_2"


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
        "mappings",
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
    assert dates.data(0, Qt.UserRole) is None  # only a step on the way to a name
    one = child(dates, "dates.session_1")  # a span is a name: every date of it
    assert one.data(0, Qt.UserRole) == "dates.session_1" and one.text(1) == "14 dates"
    week = child(one, "dates.session_1.week_2")
    assert week.text(1) == "7 dates" and not week.childCount()
    assert child(dates, "dates.mondays").text(1) == "3 dates"
    window.editor.clear()
    window.names.setCurrentItem(dates)  # not a name: nothing is inserted
    window.names._pick_current()
    assert window.editor.skedge_edit.toPlainText() == ""
    window.names.setCurrentItem(week)
    window.names._pick_current()
    assert window.editor.skedge_edit.toPlainText() == "dates.session_1.week_2"


def test_right_clicking_a_calendar_day_can_make_it_the_target(window, monkeypatch):
    from puppet_strings.app import calendar_pane

    calendar = window.calendar
    calendar.setCurrentPage(2026, 9)
    view, cells = calendar.view, {}
    for row in range(1, view.model().rowCount()):
        for column in range(1, view.model().columnCount()):
            index = view.model().index(row, column)
            day = calendar.date_at(view.visualRect(index).center())
            assert day.day == int(index.data()), (row, column)  # the day Qt drew there
            cells[day] = index
    assert (
        date(2026, 9, 18) in cells
        and calendar.date_at(view.visualRect(view.model().index(1, 0)).center()) is None
    )  # the week labels are no day
    chosen = []

    class Menu:  # stands in for the menu, choosing its one action at once
        def __init__(self, parent):
            pass

        def addAction(self, text, act):  # noqa: N802
            chosen.append(text)
            self.act = act

        def exec(self, point):
            self.act()

    monkeypatch.setattr(calendar_pane, "QMenu", Menu)
    view.customContextMenuRequested.emit(view.visualRect(cells[date(2026, 9, 18)]).center())
    assert chosen == ["Set as target"]
    window.wait_for_load()
    assert window.target == date(2026, 9, 18) == window.store.dataset.target


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


def test_the_clinics_are_made_from_the_offerings_tab_and_not_saved(window):
    made = [r for r in window.store.requests if "clinic_import" in r.tags]
    assert len(made) == 24 and all(r.priority.value == "CLINIC" for r in made)
    assert not any("clinic_import" in r.tags for r in window.store.book.every())


def test_deleting_an_edited_clinic_puts_back_the_offerings_tabs(window, informed):
    from dataclasses import replace

    riflery = "offering:2026-09-16:riflery:clinic_3"
    made = window.model.request(riflery)
    window.store.save(replace(made, description="riflery, edited"), riflery)
    window.reload()
    window.wait_for_load()
    assert window.model.request(riflery).description == "riflery, edited"
    before = window.model.rowCount()
    window._deleted(riflery)
    assert not informed  # nothing refused: the edits are what goes
    assert window.model.rowCount() == before
    assert window.model.request(riflery) == made
    assert riflery not in {r.id for r in window.store.book.every()}
    assert "back to the Offerings tab's" in window.status_label.text()


def test_reloading_a_day_with_no_spreadsheet_makes_one(window):
    where = "root/2026/Main Season/Session 2/Monday_1"
    assert not (window.store.source.root / where).exists()
    window.date_edit.setDate(QDate(2026, 9, 28))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    assert window.store.dataset.target == date(2026, 9, 28)
    assert "Offerings" in window.store.source.tabs(where)
    made = [r for r in window.store.requests if "clinic_import" in r.tags]
    assert len(made) == len(window.store.dataset.offerings) > 0  # from the template's grid


def test_an_imported_clinic_is_not_deleted_but_sent_to_the_offerings_tab(window, informed):
    riflery = "offering:2026-09-16:riflery:clinic_3"
    window._deleted(riflery)
    window.delete_requests([window.model.request(riflery), window.model.request("breaks")])
    assert window.model.request(riflery) is not None and window.model.request("breaks")
    assert len(informed) == 2 and "Offerings tab" in informed[0]


def test_reload_picks_up_a_request_deleted_from_the_file(window):
    index = window.proxy.index(0, 0)
    window.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectCurrent)
    shown = window.editor.original_id
    delete_requests(window.store.source.root, '"id" = ?', shown)
    window.reload()
    window.reload()  # a second click while loading queues another load, not a no-op
    window.wait_for_load()
    assert window.model.rowCount() == 30
    assert window.model.request(shown) is None
    assert window.editor.original_id is None and window.loader is None


def test_solve_uses_requests_saved_since_the_last_reload(app, tmp_path):

    copy = tmp_path / "fresh"
    shutil.copytree(FIXTURES, copy)
    window = make_window(copy)
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


def test_publishing_puts_a_panel_up_and_writes_on_a_thread(window, app, monkeypatch):
    """A dozen requests to Google with the dialog unpainted reads as a hung window."""
    from puppet_strings.app.schedule_dialog import ScheduleDialog
    from puppet_strings.solver.result import Result

    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: said.append(a[2]))
    result = Result(feasible=True, assignments=())
    dialog = ScheduleDialog(window.store.source, window.store.config, window.store.current, result)
    dialog.publish_button.click()
    assert dialog.busy is not None and dialog.busy.isVisible()  # up while it is written
    assert not dialog.busy.cancel_button.isVisible()  # half a published day is no better
    assert not dialog.publish_button.isEnabled()
    dialog.wait_for_publish()
    app.processEvents()
    assert dialog.busy is None and said == ["Published 2026-09-16."]
    assert dialog.already_published
    written = window.store.source.read("root/2026/Main Season/Session 1/Wednesday_1", "Staff View")
    assert written[1][0] == "Staff"


def test_a_publish_that_fails_can_be_tried_again(window, monkeypatch):
    from puppet_strings.app.schedule_dialog import ScheduleDialog
    from puppet_strings.solver.result import Result

    complaints = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: complaints.append(a[1]))
    monkeypatch.setattr(
        "puppet_strings.app.schedule_dialog.publish",
        lambda *a: (_ for _ in ()).throw(RuntimeError("Google said no")),
    )
    dialog = ScheduleDialog(
        window.store.source, window.store.config, window.store.current, Result(feasible=True)
    )
    dialog.publish_button.click()
    dialog.wait_for_publish()
    assert complaints == ["Could not publish"]
    assert dialog.publish_button.isEnabled() and dialog.busy is None


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

    def standing(dataset):
        alesa = dataset.staff["alesa"]
        assert dataset.staff["vic"].ral == 4  # a RAL lower
        assert alesa.resting_blocks == {"breakfast", "clinic_1", "clinic_2"}  # by block start
        assert "alesa" in dataset.staff_categories["all"]  # she works the afternoon

    # applied at once, before anything is written, and nothing is read again
    standing(window.store.dataset)
    assert "Adjustments" not in window.store.source.tabs("config")
    window.write_adjustments()
    assert window.loader is None
    window.wait_for_adjustments()
    written = window.store.source.read("config", "Adjustments")
    assert ["2026-09-16", "Alesa", "morning", "", ""] in written
    assert ["2026-09-16", "Vic", "", "1", "short sleep"] in written

    window.reload()  # and the sheet says the same as the window did
    window.wait_for_load()
    standing(window.store.dataset)

    sickness = SameDayDialog(window.store, SICKNESS, window)
    sickness.staff_box.setCurrentText("Vic")
    sickness.remove_button.click()
    assert window.store.dataset.staff["vic"].ral == 5
    window.write_adjustments()
    window.wait_for_adjustments()
    assert [row[1] for row in window.store.source.read("config", "Adjustments")[1:]] == ["Alesa"]


def test_closing_the_dialog_writes_in_the_background_without_a_reload(window, monkeypatch):
    from puppet_strings.app.same_day import SLEEP, SameDayDialog

    def record(dialog):
        dialog.staff_box.setCurrentText("Vic")
        dialog.apply_button.click()

    monkeypatch.setattr(SameDayDialog, "exec", record)
    window.open_same_day(SLEEP)
    assert window.loader is None and "Vic is down 1 RAL today" in window.status_label.text()
    window.wait_for_adjustments()
    assert [row[1] for row in window.store.source.read("config", "Adjustments")[1:]] == ["Vic"]


def test_resting_all_day_takes_someone_out_of_every_category_at_once(window):
    from puppet_strings.app.same_day import SICKNESS, SameDayDialog

    sickness = SameDayDialog(window.store, SICKNESS, window)
    sickness.staff_box.setCurrentText("Vic")
    sickness.resting_box.setCurrentText(resting_label(Rest.ALL_DAY))
    sickness.apply_button.click()
    assert not any("vic" in m for m in window.store.dataset.staff_categories.values())
    sickness.remove_button.click()
    assert "vic" in window.store.dataset.staff_categories["all"]


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
    window.write_adjustments()
    window.wait_for_adjustments()
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
    saved = saved_requests(window.store.source.root)
    assert saved["dylan-off-ropes"].group == "Ropes rewrite"  # one group, the one it moved to
    assert group_rows(window)["Special weekly requests"] == 2  # it left the shelf it was on
    window.groups.dropped.emit(["breaks"], UNGROUPED)  # dragged off every shelf
    assert group_rows(window)["Ropes rewrite"] == 1
    assert next(r for r in window.store.requests if r.id == "breaks").group == ""


def request_drag(window, ids):
    """The mime data a row being dragged out of the table carries."""
    from PySide6.QtCore import QItemSelectionModel

    selection = window.table.selectionModel()
    selection.clearSelection()
    for row in range(window.proxy.rowCount()):
        if window.proxy.data(window.proxy.index(row, 0)) in ids:
            selection.select(
                window.proxy.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows
            )
    return window.proxy.mimeData(selection.selectedIndexes())


def over(pane, group):
    """The middle of a group's row in the pane, where a drop on it would land."""
    row = next(i for i in range(pane.list.count()) if pane.list.item(i).data(Qt.UserRole) == group)
    return pane.list.visualItemRect(pane.list.item(row)).center()


def test_a_drag_is_taken_wherever_it_crosses_into_the_groups(window, monkeypatch):
    """A refused drag enter costs the whole drag: no move event follows it.

    `All requests` heads the list, so it is the row most drags come in over. Refusing them
    there is why a request sometimes could not be dropped on any group at all.
    """
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Ropes rewrite", True))
    window.groups.new_group()
    pick_group(window, ALL)  # the table shows the request being dragged
    pane, data = window.groups, request_drag(window, {"breaks"})
    buttons, keys = Qt.LeftButton, Qt.NoModifier
    enter = QDragEnterEvent(over(pane, ALL), Qt.MoveAction, data, buttons, keys)
    pane.list.dragEnterEvent(enter)
    assert enter.isAccepted()  # these are requests, whatever row they came in over

    on_all = QDragMoveEvent(over(pane, ALL), Qt.MoveAction, data, buttons, keys)
    pane.list.dragMoveEvent(on_all)
    assert not on_all.isAccepted()  # `All requests` is not a shelf

    where = over(pane, "Ropes rewrite")
    moved = QDragMoveEvent(where, Qt.MoveAction, data, buttons, keys)
    pane.list.dragMoveEvent(moved)
    assert moved.isAccepted()

    dropped = []
    pane.list.dropped.connect(lambda ids, group: dropped.append((ids, group)))
    pane.list.dropEvent(QDropEvent(where, Qt.MoveAction, data, buttons, keys))
    assert dropped == [(["breaks"], "Ropes rewrite")]


def test_the_group_under_a_drag_is_outlined_until_it_leaves(window, monkeypatch):
    from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Ropes rewrite", True))
    window.groups.new_group()
    pane, data = window.groups, request_drag(window, {"breaks"})
    buttons, keys = Qt.LeftButton, Qt.NoModifier
    pane.list.dragMoveEvent(
        QDragMoveEvent(over(pane, "Ropes rewrite"), Qt.MoveAction, data, buttons, keys)
    )
    assert pane.list.target.data(Qt.UserRole) == "Ropes rewrite"
    pane.list.dragMoveEvent(QDragMoveEvent(over(pane, ALL), Qt.MoveAction, data, buttons, keys))
    assert pane.list.target is None  # `All requests` is not a shelf, so nothing is aimed at
    pane.list.dragMoveEvent(
        QDragMoveEvent(over(pane, "Ropes rewrite"), Qt.MoveAction, data, buttons, keys)
    )
    pane.list.dragLeaveEvent(QDragLeaveEvent())
    assert pane.list.target is None


def test_a_drag_is_shown_as_a_small_token_not_the_rows(app):
    from PySide6.QtGui import QFont

    from puppet_strings.app.request_table import WIDEST, drag_token

    one = drag_token(["breaks"], QFont())
    many = drag_token([f"request-{i}" for i in range(40)], QFont())
    assert one.width() < WIDEST and one.height() < 60
    assert many.width() < WIDEST + 60 and many.height() < 80  # a count, however many
    long = drag_token(["x" * 500], QFont())
    assert long.width() <= WIDEST + 30  # a long id is elided, not the token grown


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


def test_a_group_can_say_what_scope_its_new_requests_take(window):
    window.store.group_scopes.set("Special weekly requests", "week")
    pick_group(window, "Special weekly requests")
    window.new_request()
    assert window.editor.scope_box.currentData() == window.store.dataset.scope("week")
    pick_group(window, "Special daily requests")
    window.new_request()
    assert window.editor.scope_box.currentData().kind == "session"  # nothing said
    window.store.group_scopes.set("Special weekly requests", "")


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
    assert saved_requests(window.store.source.root)["dylan-off-ropes"].requester == "rob"


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
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL dates.session_2.week_1",
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
    assert window.date_check.isChecked()  # it does nothing on the date being scheduled
    window.date_filter.setDate(QDate(2026, 9, 16))
    assert saved not in visible_ids(window)
    window.date_filter.setDate(QDate(2026, 9, 28))  # about it, but scoped to session 1
    assert saved not in visible_ids(window)
    window.date_check.setChecked(False)
    assert saved in visible_ids(window)


def test_saving_a_request_about_this_date_asks_nothing(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: pytest.fail("should not have asked")
    )
    for skedge in (
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON dates.target",
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1",  # no ON: every day
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL dates.session_1.week_1",
    ):
        editor = write_request(window, skedge, description=f"ok {skedge[-6:]}")
        editor.save_button.click()
        assert editor.original_id is not None


# -- the calendar --------------------------------------------------------------------------


# -- what a load reads, and what it leaves for later -----------------------------------------


def test_the_prefetch_reads_the_published_days_the_load_left(app, fixtures_copy):
    """The load does not wait for them; they are there by the time Solve is pressed."""
    window = make_window(fixtures_copy, loaded=False)
    window.reload()
    window.wait_for_load()
    window.wait_for_history()
    assert set(window.store.dataset.published) == {date(2026, 9, 14), date(2026, 9, 15)}


def test_the_prefetch_follows_the_day_the_window_moved_to(window):
    window.wait_for_history()
    window.date_edit.setDate(QDate(2026, 9, 17))
    window.reload()
    window.wait_for_load()
    window.wait_for_history()
    assert window.store.dataset.target == date(2026, 9, 17)
    assert window.store.dataset.published


def test_a_prefetch_that_arrives_after_the_day_has_moved_on_is_dropped(window):
    """It was asked of one day and answers for that one; the window is on another."""
    from dataclasses import replace

    window.wait_for_history()
    store = window.store
    store.dataset = replace(store.dataset, published={}, target=date(2026, 9, 17))
    asked_for = store.dataset

    def moved_on(*a, **k):
        store.dataset = replace(asked_for, target=date(2026, 9, 18))  # another load, meanwhile
        return replace(asked_for, published={date(2026, 9, 15): ()})

    store.source = store.source  # unchanged; only the read is stood in for
    import puppet_strings.app.store as store_module

    original = store_module.read_history
    store_module.read_history = moved_on
    try:
        assert store.prefetch_history() is False
    finally:
        store_module.read_history = original
    assert store.dataset.target == date(2026, 9, 18) and store.dataset.published == {}


def test_solving_finds_the_history_already_read(window):
    """That is the point of it: Solve starts without a wait for the days behind it."""
    window.wait_for_history()
    read = window.store.dataset
    assert read.published
    assert window.store.for_solving().published == read.published


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


def test_the_calendar_is_shaded_as_soon_as_the_window_opens(app, fixtures_copy):
    window = make_window(fixtures_copy, loaded=False)
    assert window.store.dataset is None
    shaded = window.calendar.dateTextFormat(QDate(2026, 9, 13)).background().color().name()
    assert shaded == palette.CAMP_DAY
    window.calendar.setCurrentPage(2026, 9)
    labelled = {window.calendar.week_of_row(r) for r in ROWS}
    assert (1, 1) in labelled


def test_the_calendar_starts_on_sunday_before_a_sheet_has_been_read(app):
    """The window paints before the load finishes, and camp's week begins on a Sunday."""
    from PySide6.QtCore import Qt

    from puppet_strings.app.calendar_pane import SessionCalendar

    fresh = SessionCalendar()
    assert fresh.firstDayOfWeek() == Qt.Sunday  # whatever the machine's locale says
    fresh.setFirstDayOfWeek(Qt.Wednesday)
    fresh.show_dataset(None)  # a load that got nowhere leaves the pane the week it knows
    assert fresh.firstDayOfWeek() == Qt.Sunday


def test_a_date_off_the_calendar_takes_the_week_of_the_nearest_camp_day(window):
    """The window opens on tomorrow, which in March is no camp day at all."""
    from datetime import date

    from PySide6.QtCore import Qt

    from puppet_strings.app.calendar_pane import _span_start

    calendar = window.store.dataset.calendar
    assert _span_start(calendar, date(2026, 3, 1)) == date(2026, 9, 13)  # session 1, not 1 Jan
    window.calendar.show_calendar(calendar, date(2026, 3, 1))
    assert window.calendar.firstDayOfWeek() == Qt.Sunday


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


# Dylan is checked off on archery and the day runs it in clinic 1, so the only thing wrong
# with this request is whatever it is put beside.
PIN_ARCHERY = (
    "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING blocks.clinic_1 ON dates.target"
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
    assert window.errors.topLevelItemCount() == 0
    assert window.errors_dock.windowTitle() == "Errors"
    assert "No conflicts" in window.status_label.text()
    assert "No errors" in window.status_label.text()


def test_saving_a_contradiction_groups_it_in_the_pane(window):
    riflery = save_request(window, "Dylan on archery", PIN_ARCHERY)
    assert window.errors.topLevelItemCount() == 0
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    assert "it conflicts with 1 other request(s)" in window.status_label.text()
    (heading, children) = tree_rows(window.errors)[0]
    assert heading == "dylan · Wed 2026-09-16 · clinic_1"
    assert children[:2] == [riflery, free]  # grouped under the collision
    assert window.errors_dock.windowTitle() == "Errors (1)"
    heading = window.errors.topLevelItem(0)
    assert heading.text(2) == "must be free, and is asked to do archery_1_2"
    assert heading.childCount() == 2  # one reason, so it is said once, in the heading


def test_a_contradiction_the_solver_can_settle_is_not_a_conflict(window):
    """Only MUST_HAPPEN requests can make a day impossible, so only they are reported."""
    save_request(window, "Dylan on archery", PIN_ARCHERY)
    save_request(window, "Dylan is free", DYLAN_FREE, priority="HIGH")
    assert window.errors.topLevelItemCount() == 0
    assert window.errors_dock.windowTitle() == "Errors"


BAD_RIFLERY = (
    "REQUEST staff.dylan DO activities.clinics.riflery DURING blocks.clinic_2 ON dates.target"
)


def test_the_pane_holds_errors_beside_the_conflicts(window):
    """One request asking for the impossible belongs on the same list as two that disagree."""
    saved = save_request(window, "Dylan on riflery", BAD_RIFLERY, priority="HIGH")
    assert "2 error(s) in it" in window.status_label.text()
    rows = tree_rows(window.errors)
    assert [children for _, children in rows] == [[saved], [saved]]
    headings = [heading for heading, _ in rows]
    assert "dylan" in headings[0] and "clinic_2" in headings[1]
    assert window.errors_dock.windowTitle() == "Errors (2)"
    said = [window.errors.topLevelItem(i).text(2) for i in range(2)]
    assert "not checked off on 'riflery' (Skills sheet)" in said[0]
    assert "Riflery is not offered in clinic_2" in said[1]
    window.editor.clear()
    window.errors.itemDoubleClicked.emit(window.errors.topLevelItem(0).child(0), 0)
    assert window.editor.original_id == saved  # the row under an error opens it


def test_an_error_goes_when_the_request_that_asks_for_it_does(window):
    saved = save_request(window, "Dylan on riflery", BAD_RIFLERY, priority="HIGH")
    window.editor.show_request(window.model.request(saved))
    window.editor.delete_button.click()
    assert window.errors.topLevelItemCount() == 0
    assert window.errors_dock.windowTitle() == "Errors"


def test_a_request_appears_under_every_collision_it_is_in(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)  # other dates
    wednesday = [
        save_request(window, "Dylan is free", DYLAN_FREE),
        save_request(window, "Dylan on archery", PIN_ARCHERY),
    ]
    friday = [
        save_request(window, "Friday archery", PIN_ARCHERY.replace("dates.target", "2026-09-18")),
        save_request(window, "Friday free", DYLAN_FREE.replace("dates.target", "2026-09-18")),
    ]
    rows = tree_rows(window.errors)
    assert [heading for heading, _ in rows] == [
        "dylan · Wed 2026-09-16 · clinic_1",
        "dylan · Fri 2026-09-18 · clinic_1",
    ]
    assert [sorted(c for c in children if c) for _, children in rows] == [
        sorted(wednesday),
        sorted(friday),
    ]


def test_deleting_a_request_clears_its_conflict(window):
    save_request(window, "Dylan on archery", PIN_ARCHERY)
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    assert window.errors.topLevelItemCount() == 1
    window.editor.show_request(window.model.request(free))
    window.editor.delete_button.click()
    assert window.errors.topLevelItemCount() == 0
    assert window.errors_dock.windowTitle() == "Errors"


def conflict_child(window, request_id):
    """The row for one request under the first collision in the pane."""
    heading = window.errors.topLevelItem(0)
    rows = (heading.child(i) for i in range(heading.childCount()))
    return next(row for row in rows if row.text(0) == request_id)


def test_double_clicking_a_conflict_opens_that_request(window):
    riflery = save_request(window, "Dylan on archery", PIN_ARCHERY)
    save_request(window, "Dylan is free", DYLAN_FREE)
    window.editor.clear()
    window.errors.itemDoubleClicked.emit(conflict_child(window, riflery), 0)
    assert window.editor.original_id == riflery
    heading = window.errors.topLevelItem(0)
    window.errors.itemDoubleClicked.emit(heading, 0)  # the heading is not a request
    assert window.editor.original_id == riflery


def test_a_conflicting_request_opens_even_when_the_group_hides_it(window):
    save_request(window, "Dylan on archery", PIN_ARCHERY)
    free = save_request(window, "Dylan is free", DYLAN_FREE)
    pick_group(window, "Special daily requests")
    assert free not in visible_ids(window)
    window.editor.clear()
    window.errors.itemDoubleClicked.emit(conflict_child(window, free), 0)
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
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL dates.session_2.week_1",
    )
    editor.save_button.click()
    assert editor.save_button.text() == "Save" and editor.save_button.isEnabled()
    assert editor.status.text() == "Not saved; still editing"
    assert f"color: {palette.QUIET}" in editor.status.styleSheet()


def test_saving_shows_a_conflict_in_the_confirmation(window):
    save_request(window, "Dylan on archery", PIN_ARCHERY)
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


def test_double_clicking_a_mapping_opens_its_table(window, monkeypatch):
    from puppet_strings.app import main as main_module

    opened = []
    monkeypatch.setattr(
        main_module, "MappingDialog", lambda *args, **kwargs: FakeDialog(opened, args[2])
    )
    mappings = next(
        window.names.topLevelItem(i)
        for i in range(window.names.topLevelItemCount())
        if window.names.topLevelItem(i).text(0) == "mappings"
    )
    window.names.itemDoubleClicked.emit(child(mappings, "mappings.preference"), 0)
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


def test_a_date_that_fails_to_load_says_so_once(window, monkeypatch):
    """Leaving the date box is not a request to read the same broken day again."""
    critical = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: critical.append(a))
    real_load = window.store.load

    def load(target):
        if target == date(2026, 9, 18):
            raise LoadError("Mappings/mapping_buddy row ['leandro']: not in staff.counselors")
        real_load(target)

    monkeypatch.setattr(window.store, "load", load)
    window.date_edit.setDate(QDate(2026, 9, 18))
    window._target_changed()
    window.wait_for_load()
    for _ in range(3):  # what every click elsewhere does
        window.date_edit.editingFinished.emit()
        window.wait_for_load()
    assert len(critical) == 1
    window.reload()  # Reload still means read it again
    window.wait_for_load()
    assert len(critical) == 2
    window.date_edit.setDate(QDate(2026, 9, 15))  # and another date loads as usual
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    assert window.store.dataset.target == date(2026, 9, 15)
    assert len(critical) == 2


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
    from puppet_strings.app.errors_panel import _group

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


def test_the_editor_keeps_a_request_in_its_own_scope(window):
    """A request's scope is when it applies, so editing one must not move it."""
    editor = window.editor
    editor.show_request(window.model.request("breaks"))
    assert editor.scope_box.currentText() == "Season: 2026"
    assert [editor.scope_box.itemText(i) for i in range(editor.scope_box.count())] == [
        "Day: Wed Sep 16",
        "Week: Sep 13 to Sep 19",
        "Session: Sep 13 to Sep 26",
        "Season: 2026",
    ]
    editor.save_button.click()
    assert saved_requests(window.store.source.root)["breaks"].scope.kind == "season"
    editor.clear()
    assert editor.scope_box.currentData().kind == "session"  # a new one is this session's


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


def test_every_keyword_the_grammar_has_is_a_keyword_to_the_editor():
    """The one list the box colours by, checked against the one the parser reads by."""
    import re

    from puppet_strings.app.editor import KEYWORD_WORDS, is_keyword

    grammar = (Path(puppet_strings.__file__).parent / "skedge" / "grammar.lark").read_text()
    words = set(re.findall(r"/([A-Z_]+)\\b/i", grammar))
    assert len(words) > 20
    assert words <= set(KEYWORD_WORDS), sorted(words - set(KEYWORD_WORDS))
    assert is_keyword("any") and is_keyword("exclude")


def test_a_keyword_is_coloured_in_whichever_case_it_is_written_in(window):
    """Skedge reads `request` and `REQUEST` alike, so the editor colours them alike."""
    edit = window.editor.skedge_edit
    edit.setPlainText("request staff.dylan do 'x' during blocks.clinic_1")
    assert coloured(edit, "request") == palette.KEYWORD
    assert coloured(edit, "during") == palette.KEYWORD
    assert coloured(edit, "staff.dylan") == palette.NAME
    edit.setPlainText("REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    assert coloured(edit, "REQUEST") == palette.KEYWORD
    edit.setPlainText("EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks")
    assert coloured(edit, "EXCLUDE") == palette.KEYWORD
    assert coloured(edit, "ALL") == palette.KEYWORD
    assert coloured(edit, "'offsite'") == palette.STRING


# -- moving between days, and deleting many at once ------------------------------------------


def test_another_days_offerings_are_not_shown(window):
    """Offerings are the day's own: moving the date reads the new day, without the old one's.

    Each day's clinics are made from its own Offerings tab.
    """
    assert any(r.id.startswith("offering:2026-09-16:") for r in window.store.requests)
    window.date_edit.setDate(QDate(2026, 9, 17))
    window.date_edit.editingFinished.emit()  # the date box, finished with
    window.wait_for_load()
    assert window.store.dataset.target == date(2026, 9, 17)
    imported = [r for r in window.store.requests if "clinic_import" in r.tags]
    assert imported and all(r.id.startswith("offering:2026-09-17:") for r in imported)
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    generated = [r for r in window.store.requests if "clinic_import" in r.tags]
    assert generated and all(r.id.startswith("offering:2026-09-16:") for r in generated)


def test_the_same_date_is_not_read_again(window):
    window.date_edit.editingFinished.emit()
    assert window.loader is None


def select_rows(window, count: int) -> list[str]:
    """Pick the first rows that are not clinics from the Offerings tab, which do not delete."""
    selection = window.table.selectionModel()
    selection.clearSelection()
    rows = [
        i
        for i in range(window.proxy.rowCount())
        if "clinic_import" not in window.proxy.data(window.proxy.index(i, 0), Qt.UserRole).tags
    ]
    for row in rows[:count]:
        index = window.proxy.index(row, 0)
        selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
    return [r.id for r in window.selected_requests()]


def test_selected_requests_are_deleted_once_confirmed(window, monkeypatch):
    before = window.model.rowCount()
    chosen = select_rows(window, 3)
    asked = []

    def answer(_parent, _title, text, *args):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    QTest.keyClick(window.table, Qt.Key_Delete)
    assert "Delete 3 requests?" in asked[0] and all(i in asked[0] for i in chosen)
    assert window.model.rowCount() == before - 3
    kept = {r.id for r in window.store.book.every()}
    assert not kept & set(chosen)
    assert "Deleted 3 requests" in window.status_label.text()


def test_nothing_is_deleted_when_the_popup_is_cancelled(window, monkeypatch):
    before = window.model.rowCount()
    select_rows(window, 2)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Cancel)
    QTest.keyClick(window.table, Qt.Key_Delete)
    assert window.model.rowCount() == before


def test_the_on_date_box_starts_ticked_and_unticked_lists_every_date(window):
    """Ticked, the table is the target date's; unticked, it is every request in the file."""
    assert window.date_check.isChecked()
    window.date_edit.setDate(QDate(2026, 9, 17))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    other_day = "offering:2026-09-17:riflery:clinic_3"
    assert other_day not in {r.id for r in window.store.every}  # made on its own day only
    window.date_check.setChecked(False)
    assert other_day not in visible_ids(window)
    assert "offering:2026-09-16:riflery:clinic_3" in visible_ids(window)


def test_a_request_from_another_date_saves_without_being_solved(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    window.date_edit.setDate(QDate(2026, 9, 17))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    other_day = "offering:2026-09-17:riflery:clinic_3"
    request = window.model.request(other_day)
    window.store.save(replace(request, description="moved"), other_day)  # an edited clinic
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.date_edit.editingFinished.emit()
    window.wait_for_load()
    assert other_day not in {r.id for r in window.store.requests}
    assert window.model.request(other_day).description == "moved"
    assert saved_requests(window.store.source.root)[other_day].description == "moved"


def test_a_broken_request_is_not_hidden_by_the_date(window):
    """It is about no date anybody can tell, so the on-date view still shows it."""
    window.store.save(
        replace(window.model.request("breaks"), skedge="REQUEST staff.nobody_at_all FREE"), "breaks"
    )
    window.model.refresh()
    assert not window.store.facet(window.model.request("breaks")).valid
    assert window.date_check.isChecked() and "breaks" in visible_ids(window)


def test_the_group_counts_follow_the_filters(window):
    """Each group says how many rows picking it would show, whatever is filtering them."""

    def counts():
        items = [window.groups.list.item(i) for i in range(window.groups.list.count())]
        return {i.data(Qt.UserRole): int(i.text().rsplit("(", 1)[1][:-1]) for i in items}

    def rows(group):
        window.groups.list.setCurrentRow(window.groups._row_of(group))
        return window.proxy.rowCount()

    for change in (
        lambda: window.date_check.setChecked(False),
        lambda: window.date_check.setChecked(True),
        lambda: window.tag_filter.setCurrentText("clinic_import"),
        lambda: window.text_filter.setText("dylan"),
    ):
        change()
        now = counts()
        assert now == {group: rows(group) for group in now}
    window.tag_filter.setCurrentIndex(0)
    window.text_filter.setText("")
    window.date_check.setChecked(False)
    made = len(window.store.dataset.offerings)  # the day's clinics, which are not saved
    assert counts()[ALL] == len(window.store.every) == window.store.book.count() + made


def test_before_any_load_unticking_lists_the_whole_file(app, fixtures_copy):
    """The requests file is on this computer, so it needs no date to be listed."""
    window = make_window(fixtures_copy, loaded=False)
    assert window.store.dataset is None and window.proxy.rowCount() == 0  # no date: nothing on it
    window.date_check.setChecked(False)
    assert window.proxy.rowCount() == window.store.book.count() > 0


def test_a_date_camp_is_not_running_still_lists_every_request(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window.date_edit.setDate(QDate(2026, 12, 25))
    window.reload()
    window.wait_for_load()
    assert window.store.dataset is None and window.store.requests == []
    assert window.proxy.rowCount() == 0  # nothing happens on it
    window.date_check.setChecked(False)
    assert window.proxy.rowCount() == window.store.book.count() > 0
    window.staff_filter.setCurrentIndex(1)  # a filter with nothing to resolve names against
    assert window.proxy.rowCount() == 0
    window.staff_filter.setCurrentIndex(0)
    window.table.selectRow(0)  # a request opens, scope and all, with no date loaded
    assert window.editor.original_id and window.editor.scope_box.count() == 1


def test_enter_after_a_whole_name_starts_a_new_line(window):
    """A namespace or name written in full is done; Enter ends the line, Down still picks."""
    editor = window.editor
    editor.clear()
    box = editor.skedge_edit
    for text in ("REQUEST staff", "REQUEST staff.dylan"):
        box.setPlainText("")
        QTest.keyClicks(box, text)
        assert box.completer.popup().isVisible(), text
        QTest.keyClick(box.completer.popup(), Qt.Key_Return)
        assert box.toPlainText() == text + "\n"
        assert not box.completer.popup().isVisible()
        box.suggest()  # the line has ended, so there is no name left to look up
        assert not box.completer.popup().isVisible()
    box.setPlainText("")
    QTest.keyClicks(box, "REQUEST staff")
    QTest.keyClick(box.completer.popup(), Qt.Key_Down)
    QTest.keyClick(box.completer.popup(), Qt.Key_Return)
    assert "\n" not in box.toPlainText()  # a suggestion was taken, not a line begun
    assert not box.completer.popup().isVisible()
    box.setPlainText("")
    QTest.keyClicks(box, "REQUEST staff.dyl")
    QTest.keyClick(box.completer.popup(), Qt.Key_Return)
    assert box.toPlainText() == "REQUEST staff.dylan"
