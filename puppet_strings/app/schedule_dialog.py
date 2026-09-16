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

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.publish.views import changes_view, clinic_view, report, staff_view
from puppet_strings.publish.writer import is_published, publish
from puppet_strings.sheets.source import Source, Table
from puppet_strings.solver.result import Result


class ScheduleDialog(QDialog):
    """One tab per view. Publish writes to Published Schedules after confirming."""

    def __init__(
        self, source: Source, config: Config, dataset: Dataset, result: Result, parent=None
    ):
        super().__init__(parent)
        self.source, self.config, self.dataset, self.result = source, config, dataset, result
        self.setWindowTitle(f"Schedule for {dataset.target}")
        self.resize(1100, 700)
        tabs = QTabWidget()
        if result.feasible:
            tabs.addTab(
                _table(staff_view(dataset, result.assignments, config.remainder)), "Staff View"
            )
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
        if is_published(self.source, self.dataset):
            answer = QMessageBox.question(
                self, "Already published", f"{self.dataset.target} is published. Overwrite?"
            )
            if answer != QMessageBox.Yes:
                return
        publish(self.source, self.config, self.dataset, self.result)
        QMessageBox.information(self, "Published", f"Published {self.dataset.target}.")
        self.publish_button.setEnabled(False)


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
