"""Take the screenshots in docs/img, in the app's dark palette, from the fixtures.

    python tools/screenshots.py

Each is taken offscreen from a scratch copy of tests/fixtures, with a throwaway settings
file, so nothing on this computer is read or changed: the request manager on 2026-09-16
(app.png), name completion (completer.png), the errors pane with two clashes in it
(conflicts.png) and the sleep agreement dialog on a published day (same-day.png).
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
WORK = Path(tempfile.mkdtemp(prefix="puppet-strings-shots-"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PUPPET_STRINGS_SETTINGS"] = str(WORK / "settings.json")
os.environ["PUPPET_STRINGS_CONFIG"] = str(WORK / "config.toml")

from PySide6.QtCore import QDate, QItemSelectionModel, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from puppet_strings.app import palette  # noqa: E402
from puppet_strings.app.main import MainWindow  # noqa: E402
from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.model import Priority, Request  # noqa: E402
from puppet_strings.publish.writer import publish  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from puppet_strings.solver.solve import solve  # noqa: E402

OUT = ROOT / "docs" / "img"

app = QApplication([])
palette.apply(app)


def settle():
    """Let Qt paint what it has been asked to."""
    for _ in range(30):
        app.processEvents()


def window_on(folder):
    """A window on a fresh copy of the fixtures, loaded for 2026-09-16."""
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree("tests/fixtures", folder)
    window = MainWindow(RequestStore(CsvSource(folder), Config(time_limit_seconds=10)))
    window.resize(1569, 860)
    window.show()
    window.date_edit.setDate(QDate(2026, 9, 16))
    window.reload()
    window.wait_for_load()
    window.wait_for_history()
    settle()
    return window


def composite(window, *popups):
    """The window with top-level popups painted where they sit over it."""
    image = window.grab().toImage()
    painter = QPainter(image)
    origin = window.mapToGlobal(QPoint(0, 0))
    for popup in popups:
        painter.drawPixmap(popup.mapToGlobal(QPoint(0, 0)) - origin, popup.grab())
    painter.end()
    return image


# 0. the request manager, on a group of hand-written requests
w = window_on(WORK / "app")
w.groups.list.setCurrentRow(w.groups._row_of("Special weekly requests"))
for row in range(w.proxy.rowCount()):
    index = w.proxy.index(row, 0)
    if w.proxy.data(index, Qt.UserRole).id == "dylan-off-ropes":
        rows = QItemSelectionModel.SelectCurrent | QItemSelectionModel.Rows
        w.table.selectionModel().setCurrentIndex(index, rows)
w.editor.description_edit.setCursorPosition(0)
w.table.resizeColumnsToContents()
settle()
w.grab().save(str(OUT / "app.png"))

# 1. the completer
w = window_on(WORK / "completer")
w.new_request()
editor = w.editor
editor.description_edit.setText("Counselors off ropes this week")
editor.skedge_edit.setFocus()
QTest.keyClicks(editor.skedge_edit, "REQUEST staff.c")
settle()
popup = editor.skedge_edit.completer.popup()
edit = editor.skedge_edit
image = w.grab().toImage()
painter = QPainter(image)
below = edit.viewport().mapTo(w, edit.cursorRect().bottomLeft()) + QPoint(0, 4)
painter.drawPixmap(below, popup.grab())
painter.end()
left = editor.mapTo(w, QPoint(0, 0)).x() - 10
bottom = edit.mapTo(w, QPoint(0, edit.height())).y() + 8
image.copy(QRect(left, 30, 600, bottom - 30)).save(str(OUT / "completer.png"))

# 2. the errors pane
w = window_on(WORK / "errors")
clash = [
    (
        "dylan-camp-store",
        "REQUEST staff.dylan DO 'camp store' DURING blocks.clinic_1",
        "Dylan runs the camp store in clinic 1",
    ),
    (
        "dylan-free-clinic-1",
        "REQUEST staff.dylan FREE DURING blocks.clinic_1",
        "Dylan is free in clinic 1",
    ),
    (
        "james-paperwork",
        "REQUEST staff.james DO 'paperwork' FOR 60m DURING blocks.clinic_2",
        "James does paperwork",
    ),
    (
        "james-phone-calls",
        "REQUEST staff.james DO 'phone calls' FOR 45m DURING blocks.clinic_2",
        "James makes phone calls",
    ),
]
for id, skedge, description in clash:
    w.store.save(Request(id, description, skedge, Priority.MUST_HAPPEN), None)
w._requests_changed()
settle()
w.errors.grab().copy(QRect(0, 0, 980, 200)).save(str(OUT / "conflicts.png"))

# 3. same-day changes
w = window_on(WORK / "same-day")
publish(w.store.source, w.store.config, w.store.dataset, solve(w.store.current, w.store.config))
w.reload()
w.wait_for_load()
settle()
w.same_day_action.setChecked(True)
w.editor.show_request(w.model.request("playstation-availability"))
sick = SameDayDialog(w.store, SICKNESS, w)
sick.staff_box.setCurrentText("Alesa")
sick.note_edit.setText("sick")
sick.apply_button.click()
sick.close()
sleep = SameDayDialog(w.store, SLEEP, w)
sleep.staff_box.setCurrentText("Rob")
sleep.note_edit.setText("four hours")
sleep.show()
sleep.move(w.mapToGlobal(QPoint(430, 110)))
settle()
composite(w, sleep).copy(QRect(0, 0, 1010, 620)).save(str(OUT / "same-day.png"))
shutil.rmtree(WORK, ignore_errors=True)
print(f"wrote {OUT}")
