"""Headless checks of the desktop app: models, filters, editor validation, and solving."""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
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
def window(app, tmp_path):
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    return make_window(copy)


def visible_ids(window):
    return {window.proxy.data(window.proxy.index(r, 0)) for r in range(window.proxy.rowCount())}


def test_table_and_filters(window):
    assert window.proxy.rowCount() == 30
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
    window.scope_filter.setCurrentText("week")
    assert visible_ids(window) == {"clinic-variety", "dylan-off-ropes"}
    window.scope_filter.setCurrentText("day")
    assert window.proxy.rowCount() == 24
    window.scope_filter.setCurrentIndex(0)
    window.staff_filter.setCurrentText("dylan")
    ids = visible_ids(window)
    assert "breaks" not in ids and {"dylan-off-ropes", "counselor-hours"} <= ids
    window.staff_filter.setCurrentIndex(0)
    window.activity_filter.setCurrentText("riflery")
    assert visible_ids(window) == {
        "clinic-enjoyment",
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
    editor.skedge_edit.setPlainText("DURING block.nope\nTASK 'x'")
    assert not editor.validate()
    assert "unknown block name 'nope'" in editor.status.text()
    editor.skedge_edit.setPlainText("DURING block.clinic_1\nACROSS EACH staff.counselor\nTASK 'x'")
    assert editor.validate()
    assert "3 EACH copies" in editor.status.text()
    editor.tags_edit.setText("training, week 2")
    editor.save_button.click()
    assert window.model.rowCount() == 31
    assert editor.id_label.text() == "dylan-s-day-off"
    saved = window.store.source.read("config", "Requests")
    row = next(r for r in saved if r[0] == "dylan-s-day-off")
    assert row[saved[0].index("tags")] == "training, week 2"
    assert "week 2" in window.store.tags
    editor.description_edit.setText("Dylan's day off, changed")
    editor.save_button.click()
    assert editor.id_label.text() == "dylan-s-day-off"  # editing keeps the id
    assert window.model.rowCount() == 31
    editor.clear()
    editor.description_edit.setText("Dylan's day off")
    editor.skedge_edit.setPlainText("DURING block.clinic_1\nTASK 'x'")
    editor.validate()  # the editor validates 300 ms after typing; tests cannot wait
    editor.save_button.click()
    assert editor.id_label.text() == "dylan-s-day-off-2"
    editor.delete_button.click()
    assert window.model.rowCount() == 31
    window._deleted("dylan-s-day-off")
    assert window.model.rowCount() == 30


def test_selecting_a_row_fills_the_editor(window):
    index = window.proxy.index(0, 0)
    window.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectCurrent)
    assert window.editor.id_label.text() == window.proxy.data(index)


def completions(editor):
    model = editor.skedge_edit.completer.completionModel()
    return [model.index(i, 0).data() for i in range(model.rowCount())]


def test_completer_opens_after_a_namespace_and_a_dot(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "ACROSS staff")
    assert not editor.skedge_edit.completer.popup().isVisible()
    QTest.keyClicks(editor.skedge_edit, ".")
    assert editor.skedge_edit.completer.completionPrefix() == "staff."
    assert "staff.dylan" in completions(editor) and "staff.counselor" in completions(editor)
    assert "activity.riflery" not in completions(editor)


def test_completer_narrows_as_the_name_is_typed(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "DURING block.cl")
    assert completions(editor) == [
        "block.clinic_1",
        "block.clinic_2",
        "block.clinic_3",
        "block.clinic_4",
    ]
    QTest.keyClicks(editor.skedge_edit, "inic_3")
    assert completions(editor) == ["block.clinic_3"]
    QTest.keyClicks(editor.skedge_edit, "9")
    assert completions(editor) == []
    assert not editor.skedge_edit.completer.popup().isVisible()


def test_choosing_a_completion_replaces_what_was_typed(window):
    editor = window.editor
    editor.clear()
    QTest.keyClicks(editor.skedge_edit, "ON date.sec")
    assert "date.second_thursday" in completions(editor)
    editor.skedge_edit.completer.activated.emit("date.second_thursday")
    assert editor.skedge_edit.toPlainText() == "ON date.second_thursday"


def test_completer_stays_shut_for_plain_words_and_dates(window):
    editor = window.editor
    editor.clear()
    for text in ("TASK ", "ON 2026-09-16", "AVOID 'break'"):
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
    QTest.keyClicks(window.editor.skedge_edit, "ACROSS staff.cam")
    assert completions(window.editor) == ["staff.cam_vl"]


def test_names_panel_lists_namespaces(window):
    names = window.names
    assert [names.topLevelItem(i).text(0) for i in range(names.topLevelItemCount())] == [
        "staff",
        "activity",
        "block",
        "date",
        "role",
        "metric",
    ]
    assert names.topLevelItem(3).child(0).text(0).startswith("date.")
    staff = names.topLevelItem(0)
    assert any(staff.child(i).text(0) == "staff.cam_vl" for i in range(staff.childCount()))
    names.picked.emit("staff.dylan")
    assert window.editor.skedge_edit.toPlainText().endswith("staff.dylan")


def test_calendar_click_inserts_a_date(window):
    window.editor.clear()
    window.editor.skedge_edit.setPlainText("ON ")
    window.editor.skedge_edit.moveCursor(QTextCursor.End)
    window.calendar.clicked.emit(QDate(2026, 9, 18))
    assert window.editor.skedge_edit.toPlainText() == "ON 2026-09-18"
    assert window.calendar.minimumDate() < QDate(2000, 1, 1)  # any date can be picked
    assert (
        window.calendar.dateTextFormat(QDate(2026, 9, 13)).background().color().name() == "#d6efe6"
    )
    assert window.calendar.dateTextFormat(QDate(2026, 9, 30)).background().style() == Qt.NoBrush
    window.calendar.clicked.emit(QDate(2026, 10, 2))
    assert window.editor.skedge_edit.toPlainText().endswith("2026-10-02")


def test_load_offerings_mirrors_the_offerings_tab(window):
    from dataclasses import replace

    before = window.model.rowCount()
    window.load_offerings()
    assert window.model.rowCount() == before
    assert "Loaded 24 offerings" in window.status_label.text()
    # a clinic removed from the Offerings tab disappears on the next load
    trimmed = [o for o in window.store.dataset.offerings if o.activity != "riflery"]
    window.store.dataset = replace(window.store.dataset, offerings=tuple(trimmed))
    window.load_offerings()
    assert window.model.rowCount() == before - 1
    assert not [r for r in window.store.requests if "riflery" in r.id]
    generated = [r for r in window.store.requests if "generated" in r.tags]
    assert len(generated) == 23 and all(r.priority.value == "CLINIC" for r in generated)


def test_reload_picks_up_a_row_deleted_on_the_sheet(window):
    import csv

    path = window.store.source.root / "config" / "Requests.csv"
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
    assert window.model.rowCount() == 29
    assert window.model.request(shown) is None
    assert window.editor.original_id is None and window.loader is None


def test_solve_uses_requests_saved_since_the_last_reload(app, tmp_path):
    import csv

    copy = tmp_path / "fresh"
    shutil.copytree(FIXTURES, copy)
    path = copy / "config" / "Requests.csv"
    with path.open(newline="") as f:
        rows = [r for r in csv.reader(f) if "generated" not in r]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    window = make_window(copy)
    assert not window.store.offerings_loaded
    window.load_offerings()  # no Reload in between
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
    sickness.resting_box.setCurrentText("Resting this morning")
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
    assert alesa.resting_blocks == {"clinic_1", "clinic_2"}  # the morning, by block start
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
    sickness.resting_box.setCurrentText("Resting this afternoon")
    sickness.apply_button.click()
    (row,) = window.store.dataset.today_adjustments
    assert row.ral_penalty == 1 and row.summary == "resting this afternoon and down 1 RAL"
    assert len(window.store.source.read("config", "Adjustments")) == 2  # one header, one row
