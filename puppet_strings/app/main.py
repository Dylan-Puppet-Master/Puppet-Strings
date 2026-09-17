"""The desktop request manager window."""

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app.editor import RequestEditor
from puppet_strings.app.facets import SCOPES
from puppet_strings.app.names_panel import NamesPanel
from puppet_strings.app.requests_model import RequestFilter, RequestsModel
from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog
from puppet_strings.app.schedule_dialog import ScheduleDialog
from puppet_strings.app.store import RequestStore
from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.sheets.source import CsvSource, LoadError, SheetsSource


def run_app(config: Config, fixtures: Path | None) -> int:
    """Open the window and run until it closes."""
    app = QApplication.instance() or QApplication(sys.argv)
    source = CsvSource(fixtures) if fixtures else SheetsSource(config.sheets, config.credentials)
    window = MainWindow(RequestStore(source, config))
    window.show()
    window.reload()  # loads in the background; the window paints right away
    return app.exec()


class LoadWorker(QThread):
    """Reads every sheet off the UI thread."""

    done = Signal()
    failed = Signal(str)

    def __init__(self, store: RequestStore, target: date) -> None:
        super().__init__()
        self.store = store
        self.target = target

    def run(self) -> None:
        """Load and report success or the error text."""
        try:
            self.store.load(self.target)
        except LoadError as e:
            self.failed.emit(str(e))
            return
        except Exception:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(traceback.format_exc())
            return
        self.done.emit()


class SolveWorker(QThread):
    """Runs the solver off the UI thread. The solver is imported on first use, not at startup."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, store: RequestStore, same_day: bool) -> None:
        super().__init__()
        self.store = store
        self.same_day = same_day

    def run(self) -> None:
        """Solve and emit the result or the error text."""
        from puppet_strings.solver.solve import RequestError, solve  # already imported by run_solve

        try:
            self.done.emit(solve(self.store.current, self.store.config, self.same_day))
        except (RequestError, LoadError) as e:
            self.failed.emit(str(e))
        except Exception:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    """Request table with filters on the left, editor on the right, names panel docked."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.worker: SolveWorker | None = None
        self.loader: LoadWorker | None = None
        self.reload_requested = False
        self.setWindowTitle("Puppet Strings")
        self.resize(1300, 800)

        self.model = RequestsModel(store)
        self.proxy = RequestFilter(store)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._select)
        self.editor = RequestEditor()
        self.editor.saved.connect(self._saved)
        self.editor.deleted.connect(self._deleted)
        self.names = NamesPanel()
        self.names.picked.connect(self.editor.insert_name)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.clicked.connect(self.insert_date)

        self._build_toolbar()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(self._build_filters())
        left_layout.addWidget(self.table)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        names_dock = QDockWidget("Names", self)
        names_dock.setWidget(self.names)
        self.addDockWidget(Qt.RightDockWidgetArea, names_dock)
        calendar_dock = QDockWidget("Calendar: click a date to insert it", self)
        calendar_dock.setWidget(self.calendar)
        self.addDockWidget(Qt.RightDockWidgetArea, calendar_dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel("Target date "))
        self.date_edit = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        toolbar.addWidget(self.date_edit)
        toolbar.addAction("Reload", self.reload)
        toolbar.addAction("Load offerings", self.load_offerings)
        toolbar.addAction("Solve", self.run_solve)
        toolbar.addSeparator()
        self.same_day_action = toolbar.addAction("Same-day changes")
        self.same_day_action.setCheckable(True)
        self.same_day_action.setToolTip("Re-solve a published day, moving as few people as it can")
        self.same_day_action.toggled.connect(self._same_day_toggled)
        self.sleep_action = toolbar.addAction(SLEEP, lambda: self.open_same_day(SLEEP))
        self.sickness_action = toolbar.addAction(SICKNESS, lambda: self.open_same_day(SICKNESS))
        for action in (self.sleep_action, self.sickness_action):
            action.setVisible(False)  # only while changing a day that is already out
        self.status_label = QLabel("")
        toolbar.addWidget(self.status_label)

    def _build_filters(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("search id, description, skedge")
        self.priority_filter = _combo(["any priority"] + [p.value for p in Priority])
        self.scope_filter = _combo(["any scope", *SCOPES])
        self.tag_filter = _combo(["any tag"])
        self.staff_filter = _combo(["any staff"])
        self.activity_filter = _combo(["any activity"])
        self.date_check = QCheckBox("on date")
        self.date_filter = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setCalendarPopup(True)
        combos = (
            self.priority_filter,
            self.scope_filter,
            self.tag_filter,
            self.staff_filter,
            self.activity_filter,
        )
        for widget in (self.text_filter, *combos, self.date_check, self.date_filter):
            layout.addWidget(widget)
        self.text_filter.textChanged.connect(self.apply_filters)
        for combo in combos:
            combo.currentIndexChanged.connect(self.apply_filters)
        self.date_check.toggled.connect(self.apply_filters)
        self.date_filter.dateChanged.connect(self.apply_filters)
        return layout

    def apply_filters(self) -> None:
        """Push the filter widgets' state into the proxy model."""
        self.proxy.set_filters(
            text=self.text_filter.text(),
            priority=_choice(self.priority_filter),
            scope=_choice(self.scope_filter),
            tag=_choice(self.tag_filter),
            staff=_choice(self.staff_filter),
            activity=_choice(self.activity_filter),
            date=self.date_filter.date().toPython() if self.date_check.isChecked() else None,
        )

    @property
    def target(self) -> date:
        """The date in the toolbar."""
        return self.date_edit.date().toPython()

    def reload(self) -> None:
        """Read every sheet again for the target date, in the background.

        A click while a load is running queues one more load for when it finishes.
        """
        if self.loader is not None:
            self.reload_requested = True
            return
        self.status_label.setText(f"  Loading {self.target}…")
        self.loader = LoadWorker(self.store, self.target)
        self.loader.done.connect(self._loaded)
        self.loader.failed.connect(self._load_failed)
        self.loader.finished.connect(self._load_finished)
        self.loader.start()

    def wait_for_load(self) -> None:
        """Block until background loads finish (used by tests)."""
        while self.loader is not None:
            self.loader.wait()
            QApplication.processEvents()

    def _load_finished(self) -> None:
        """The thread has stopped: drop it, and start the queued reload if any."""
        self.loader = None
        if self.reload_requested:
            self.reload_requested = False
            self.reload()

    def _loaded(self) -> None:
        dataset = self.store.dataset
        if self.editor.original_id and self.model.request(self.editor.original_id) is None:
            self.editor.clear()  # the request shown was deleted on the sheet
        self.model.refresh()
        self.table.resizeColumnsToContents()
        self.editor.set_dataset(dataset)
        self.names.show_dataset(dataset)
        self._fill_combo(self.staff_filter, "any staff", sorted(dataset.staff))
        self._fill_combo(self.activity_filter, "any activity", sorted(dataset.activities))
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self._mark_camp_days(dataset)
        self._refresh_same_day()
        today = [a.describe(dataset.staff[a.staff].name) for a in dataset.today_adjustments]
        state = "published" if dataset.baseline is not None else "not published"
        parts = [f"Loaded {len(self.store.requests)} requests", f"{dataset.target} is {state}"]
        self.status_label.setText("  " + ". ".join(parts + today + list(dataset.warnings)))

    def _mark_camp_days(self, dataset) -> None:
        """Shade the dates on the Calendar sheet; any date can still be picked."""
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())  # clear old marks
        camp_day = QTextCharFormat()
        camp_day.setBackground(QColor("#d6efe6"))
        for day in dataset.calendar:
            self.calendar.setDateTextFormat(QDate(day), camp_day)
        self.calendar.setSelectedDate(QDate(dataset.target))
        self.calendar.setCurrentPage(dataset.target.year, dataset.target.month)

    def _load_failed(self, message: str) -> None:
        self.status_label.setText("")
        QMessageBox.critical(self, "Could not load", message)

    @property
    def same_day(self) -> bool:
        """Whether the next solve should hold the published schedule together."""
        dataset = self.store.dataset
        checked = self.same_day_action.isChecked()
        return checked and dataset is not None and dataset.baseline is not None

    def _same_day_toggled(self, on: bool) -> None:
        """Turning it on moves to today, since that is the day people are changing."""
        dataset = self.store.dataset
        if on and dataset is not None and dataset.baseline is None:
            self.date_edit.setDate(QDate(date.today()))
            self.reload()
        self._refresh_same_day()

    def _refresh_same_day(self) -> None:
        """Same-day changes only make sense for a day that has been published."""
        dataset = self.store.dataset
        published = dataset is not None and dataset.baseline is not None
        self.same_day_action.setEnabled(published)
        if not published and self.same_day_action.isChecked():
            self.same_day_action.blockSignals(True)
            self.same_day_action.setChecked(False)
            self.same_day_action.blockSignals(False)
        for action in (self.sleep_action, self.sickness_action):
            action.setVisible(self.same_day)

    def open_same_day(self, kind: str) -> None:
        """Record a sleep agreement or a sickness for today."""
        if self.store.dataset is None:
            return
        dialog = SameDayDialog(self.store, kind, self)
        dialog.exec()
        if dialog.changed:
            self.reload()  # standing feeds eligibility, so read everything again

    def load_offerings(self) -> None:
        """Add the Offerings tab's clinics to the Requests sheet as generated requests."""
        if self.store.dataset is None:
            return
        count = self.store.load_offerings()
        self.model.refresh()
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self.status_label.setText(f"  Loaded {count} offerings for {self.target}")

    def insert_date(self, day: QDate) -> None:
        """Put a clicked calendar date into the Skedge editor at the cursor."""
        self.editor.insert_name(day.toString("yyyy-MM-dd"))

    def run_solve(self) -> None:
        """Solve the target date in the background, then show the schedule dialog."""
        if self.store.dataset is None or self.worker is not None:
            return
        if not self.store.offerings_loaded:
            answer = QMessageBox.question(
                self, "No offerings loaded", f"No offerings loaded for {self.target}. Solve anyway?"
            )
            if answer != QMessageBox.Yes:
                return
        import puppet_strings.solver.solve  # noqa: F401 - import on the main thread; a QThread import crashes

        self.status_label.setText("  Solving…")
        self.worker = SolveWorker(self.store, self.same_day)
        self.worker.done.connect(self._solved)
        self.worker.failed.connect(self._solve_failed)
        self.worker.finished.connect(self._solve_finished)
        self.worker.start()

    def _solve_finished(self) -> None:
        self.worker = None

    def _solved(self, result) -> None:
        self.status_label.setText("")
        ScheduleDialog(
            self.store.source, self.store.config, self.store.current, result, self
        ).exec()

    def _solve_failed(self, message: str) -> None:
        self.status_label.setText("")
        QMessageBox.critical(self, "Solve failed", message)

    def _select(self, current, previous) -> None:
        if current.isValid():
            self.editor.show_request(self.proxy.data(current, Qt.UserRole))

    def _saved(self, request, original_id) -> None:
        saved = self.store.save(request, original_id)
        self.editor.saved_as(saved)
        self.model.refresh()
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self.status_label.setText(f"  Saved {saved.id}")

    def _deleted(self, request_id: str) -> None:
        self.store.delete(request_id)
        self.model.refresh()
        self.status_label.setText(f"  Deleted {request_id}")

    @staticmethod
    def _fill_combo(combo: QComboBox, first: str, items: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([first, *items])
        combo.setCurrentText(current if current in items else first)
        combo.blockSignals(False)


def _combo(items: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    return combo


def _choice(combo: QComboBox) -> str | None:
    return None if combo.currentIndex() == 0 else combo.currentText()
