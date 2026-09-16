"""Headless checks of the desktop app: models, filters, editor validation, and solving."""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from tests.conftest import FIXTURES  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    window = MainWindow(RequestStore(CsvSource(copy), Config(time_limit_seconds=10)))
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.reload()
    window.wait_for_load()
    return window


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
    window = MainWindow(RequestStore(CsvSource(copy), Config(time_limit_seconds=10)))
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.reload()
    window.wait_for_load()
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
