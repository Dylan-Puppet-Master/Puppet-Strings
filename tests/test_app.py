"""Headless checks of the desktop app: models, filters, editor validation, and solving."""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QItemSelectionModel  # noqa: E402
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
    return window


def visible_ids(window):
    return {window.proxy.data(window.proxy.index(r, 0)) for r in range(window.proxy.rowCount())}


def test_table_and_filters(window):
    assert window.proxy.rowCount() == 6
    window.text_filter.setText("counselor hour")
    assert visible_ids(window) == {"counselor-hours"}
    window.text_filter.setText("")
    window.priority_filter.setCurrentText("MUST_HAPPEN")
    assert window.proxy.rowCount() == 3
    window.priority_filter.setCurrentIndex(0)
    window.scope_filter.setCurrentText("week")
    assert visible_ids(window) == {"clinic-variety", "dylan-off-ropes"}
    window.scope_filter.setCurrentIndex(0)
    window.staff_filter.setCurrentText("dylan")
    ids = visible_ids(window)
    assert "breaks" not in ids and {"dylan-off-ropes", "counselor-hours"} <= ids
    window.staff_filter.setCurrentIndex(0)
    window.activity_filter.setCurrentText("riflery")
    assert visible_ids(window) == {"clinic-enjoyment", "clinic-variety"}
    window.activity_filter.setCurrentIndex(0)
    window.date_check.setChecked(True)
    window.date_filter.setDate(QDate(2026, 9, 19))
    ids = visible_ids(window)
    assert "dylan-off-ropes" not in ids and "breaks" in ids


def test_editor_validation_and_save(window):
    editor = window.editor
    editor.clear()
    editor.id_edit.setText("new-request")
    editor.skedge_edit.setPlainText("DURING block.nope\nTASK 'x'")
    assert not editor.validate()
    assert "unknown block name 'nope'" in editor.status.text()
    editor.skedge_edit.setPlainText("DURING block.clinic_1\nACROSS EACH staff.counselor\nTASK 'x'")
    assert editor.validate()
    assert "3 EACH copies" in editor.status.text()
    editor.save_button.click()
    assert window.model.rowCount() == 7
    saved = window.store.source.read("config", "Requests")
    assert any(row[0] == "new-request" for row in saved)
    editor.delete_button.click()
    assert window.model.rowCount() == 6


def test_selecting_a_row_fills_the_editor(window):
    index = window.proxy.index(0, 0)
    window.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectCurrent)
    assert window.editor.id_edit.text() == window.proxy.data(index)


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


def test_solve_worker_produces_a_result(window, app):
    results = []
    window.run_solve()
    window.worker.done.disconnect()
    window.worker.done.connect(results.append)
    window.worker.wait(60000)
    app.processEvents()
    assert results and results[0].feasible
