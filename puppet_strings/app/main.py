"""The desktop request manager window."""

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
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
from puppet_strings.app.schedule_dialog import ScheduleDialog
from puppet_strings.app.store import RequestStore
from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.sheets.source import CsvSource, LoadError, SheetsSource
from puppet_strings.solver.solve import RequestError, solve


def run_app(config: Config, fixtures: Path | None) -> int:
    """Open the window and run until it closes."""
    app = QApplication.instance() or QApplication(sys.argv)
    source = CsvSource(fixtures) if fixtures else SheetsSource(config.sheets, config.credentials)
    window = MainWindow(RequestStore(source, config))
    window.show()
    window.reload()
    return app.exec()


class SolveWorker(QThread):
    """Runs the solver off the UI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store

    def run(self) -> None:
        """Solve and emit the result or the error text."""
        try:
            self.done.emit(solve(self.store.dataset, self.store.config))
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
        dock = QDockWidget("Names", self)
        dock.setWidget(self.names)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel("Target date "))
        self.date_edit = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        toolbar.addWidget(self.date_edit)
        toolbar.addAction("Reload", self.reload)
        toolbar.addAction("Solve", self.run_solve)
        self.status_label = QLabel("")
        toolbar.addWidget(self.status_label)

    def _build_filters(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("search id, description, skedge")
        self.priority_filter = _combo(["any priority"] + [p.value for p in Priority])
        self.scope_filter = _combo(["any scope", *SCOPES])
        self.staff_filter = _combo(["any staff"])
        self.activity_filter = _combo(["any activity"])
        self.date_check = QCheckBox("on date")
        self.date_filter = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setCalendarPopup(True)
        for widget in (
            self.text_filter,
            self.priority_filter,
            self.scope_filter,
            self.staff_filter,
            self.activity_filter,
            self.date_check,
            self.date_filter,
        ):
            layout.addWidget(widget)
        self.text_filter.textChanged.connect(self.apply_filters)
        for combo in (
            self.priority_filter,
            self.scope_filter,
            self.staff_filter,
            self.activity_filter,
        ):
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
            staff=_choice(self.staff_filter),
            activity=_choice(self.activity_filter),
            date=self.date_filter.date().toPython() if self.date_check.isChecked() else None,
        )

    @property
    def target(self) -> date:
        """The date in the toolbar."""
        return self.date_edit.date().toPython()

    def reload(self) -> None:
        """Read every sheet again for the target date."""
        try:
            self.store.load(self.target)
        except LoadError as e:
            QMessageBox.critical(self, "Could not load", str(e))
            return
        self.model.refresh()
        self.table.resizeColumnsToContents()
        self.editor.set_dataset(self.store.dataset)
        self.names.show_dataset(self.store.dataset)
        self._fill_combo(self.staff_filter, "any staff", sorted(self.store.dataset.staff))
        self._fill_combo(
            self.activity_filter, "any activity", sorted(self.store.dataset.activities)
        )
        warnings = "; ".join(self.store.dataset.warnings)
        self.status_label.setText(f"  Loaded {len(self.store.requests)} requests. {warnings}")

    def run_solve(self) -> None:
        """Solve the target date in the background, then show the schedule dialog."""
        if self.store.dataset is None or self.worker is not None:
            return
        self.status_label.setText("  Solving…")
        self.worker = SolveWorker(self.store)
        self.worker.done.connect(self._solved)
        self.worker.failed.connect(self._solve_failed)
        self.worker.start()

    def _solved(self, result) -> None:
        self.worker = None
        self.status_label.setText("")
        ScheduleDialog(
            self.store.source, self.store.config, self.store.dataset, result, self
        ).exec()

    def _solve_failed(self, message: str) -> None:
        self.worker = None
        self.status_label.setText("")
        QMessageBox.critical(self, "Solve failed", message)

    def _select(self, current, previous) -> None:
        if current.isValid():
            self.editor.show_request(self.proxy.data(current, Qt.UserRole))

    def _saved(self, request, original_id) -> None:
        self.store.save(request, original_id)
        self.model.refresh()
        self.status_label.setText(f"  Saved {request.id}")

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
