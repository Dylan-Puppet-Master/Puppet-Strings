"""Shows a solve result: staff view, clinic view, report, and a Publish button."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from puppet_strings.app.busy import BusyDialog
from puppet_strings.app.worker import Worker
from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.publish.views import changes_view, clinic_view, report, staff_view
from puppet_strings.publish.writer import publish
from puppet_strings.sheets.source import Source, Table
from puppet_strings.solver.result import Result


class ScheduleDialog(QDialog):
    """One tab per view. Publish writes to Published Schedules after confirming."""

    def __init__(
        self, source: Source, config: Config, dataset: Dataset, result: Result, parent=None
    ):
        super().__init__(parent)
        self.source, self.config, self.dataset, self.result = source, config, dataset, result
        self.worker: Worker | None = None
        self.busy: BusyDialog | None = None
        # Whether the day is already out. The load read the day's own assignments, so this
        # is known rather than asked: two requests saved, and no wait before the question.
        self.already_published = dataset.baseline is not None
        self.setWindowTitle(f"Schedule for {dataset.target}")
        self.resize(1100, 700)
        tabs = QTabWidget()
        if result.feasible:
            staff = staff_view(dataset, result.assignments, config.remainder)
            tabs.addTab(_table(staff.rows), "Staff View")
            clinics = clinic_view(dataset, result.assignments, config.remainder)
            tabs.addTab(_table(clinics.rows), "Clinic View")
        if result.changes:
            tabs.addTab(_table(changes_view(dataset, result)), "Changes")
        tabs.addTab(_table(report(result)), "Report")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.publish_button = buttons.addButton("Publish", QDialogButtonBox.ActionRole)
        self.publish_button.setEnabled(result.feasible)
        self.publish_button.clicked.connect(self._publish)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _publish(self) -> None:
        """Write the day out, on a thread, with a panel up saying so.

        Publishing is a dozen requests to Google and takes a few seconds; doing it here
        would leave the dialog unpainted for all of them, which reads as a hung window.
        """
        if self.worker is not None:
            return
        if self.already_published:
            answer = QMessageBox.question(
                self, "Already published", f"{self.dataset.target} is published. Overwrite?"
            )
            if answer != QMessageBox.Yes:
                return
        self.publish_button.setEnabled(False)
        self.busy = BusyDialog(f"Publishing {self.dataset.target}…", self, cancellable=False)
        self.worker = Worker(lambda: publish(self.source, self.config, self.dataset, self.result))
        self.worker.done.connect(self._published)
        self.worker.failed.connect(self._publish_failed)
        self.worker.finished.connect(self._publish_finished)
        self.worker.start()
        self.busy.show()

    def _published(self, _=None) -> None:
        self._close_busy()
        self.already_published = True
        QMessageBox.information(self, "Published", f"Published {self.dataset.target}.")

    def _publish_failed(self, message: str) -> None:
        """Say what went wrong and leave Publish where it was, so it can be tried again."""
        self._close_busy()
        self.publish_button.setEnabled(True)
        QMessageBox.critical(self, "Could not publish", message)

    def _publish_finished(self) -> None:
        self.worker = None

    def _close_busy(self) -> None:
        if self.busy is not None:
            self.busy.finish()
            self.busy = None

    def wait_for_publish(self) -> None:
        """Block until the day has been written (used by tests)."""
        from PySide6.QtWidgets import QApplication

        while self.worker is not None:
            self.worker.wait()
            QApplication.processEvents()


def _table(rows: Table) -> QTableWidget:
    width = max(len(r) for r in rows)
    body = [r + [""] * (width - len(r)) for r in rows]
    table = QTableWidget(len(body), width)
    table.horizontalHeader().hide()
    for r, row in enumerate(body):
        for c, cell in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(cell)))
    table.resizeColumnsToContents()
    table.resizeRowsToContents()
    return table
