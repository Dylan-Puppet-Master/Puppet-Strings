"""The popups a name in the Namespaces pane opens: what it stands for, and metric tables.

A metric is the one name worth changing rather than reading, so its popup is the table
itself, editable, written straight back to its tab. Everything else is a reading: who is in
a category, what an activity asks for, what the cabin act board wrote on a card.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from puppet_strings.app.details import Details
from puppet_strings.config import Config
from puppet_strings.sheets.metrics import TAB_PREFIX
from puppet_strings.sheets.source import Source

CONFIG_SHEET = "config"
SPARE_ROWS = 5  # blank rows at the bottom of a metric table, to add ratings without ceremony


class DetailsDialog(QDialog):
    """What one name stands for, a section at a time."""

    def __init__(self, found: Details, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(found.title)
        self.resize(560, 460)
        heading = QLabel(f"<b>{found.title}</b><br>{found.subtitle}")
        heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tree = QTreeWidget()
        tree.setHeaderLabels(["", ""])
        tree.setRootIsDecorated(False)
        for section in found.sections:
            top = QTreeWidgetItem([section.heading, ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            tree.addTopLevelItem(top)
            for label, value in section.rows:
                top.addChild(QTreeWidgetItem([label, value]))
            top.setExpanded(True)
        tree.resizeColumnToContents(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(tree)
        layout.addWidget(buttons)


class MetricDialog(QDialog):
    """One metric's ratings, as they are on its tab, editable.

    The tab is read again rather than rebuilt from the loaded metric: the sheet holds names
    and the loaded metric holds identifiers, and showing what is written is the only way to
    edit it and put it back unchanged apart from the edit.
    """

    def __init__(self, source: Source, config: Config, metric: str, parent=None) -> None:
        super().__init__(parent)
        self.source, self.config, self.metric = source, config, metric
        self.tab = f"{TAB_PREFIX}{metric}"
        self.setWindowTitle(f"metrics.{metric}")
        self.resize(620, 520)
        table = self.source.read(CONFIG_SHEET, self.tab)
        self.header = table[0] if table else []
        body = table[1:]
        self.grid = QTableWidget(len(body) + SPARE_ROWS, max(len(self.header), 1))
        self.grid.setHorizontalHeaderLabels(self.header)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, row in enumerate(body):
            for c in range(len(self.header)):
                self.grid.setItem(r, c, QTableWidgetItem(row[c] if c < len(row) else ""))
        for r in range(len(body), len(body) + SPARE_ROWS):
            for c in range(len(self.header)):
                self.grid.setItem(r, c, QTableWidgetItem(""))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>metrics.{metric}</b><br>{self.tab}, on the config sheet"))
        layout.addWidget(self.grid)
        layout.addWidget(buttons)

    def rows(self) -> list[list[str]]:
        """The header and every row with something written in it."""
        written = []
        for r in range(self.grid.rowCount()):
            cells = [
                (self.grid.item(r, c).text().strip() if self.grid.item(r, c) else "")
                for c in range(self.grid.columnCount())
            ]
            if any(cells):
                written.append(cells)
        return [list(self.header), *written]

    def save(self) -> None:
        """Write the tab back, and say so rather than closing on a silent failure."""
        try:
            self.source.write(CONFIG_SHEET, self.tab, self.rows())
        except Exception as e:  # noqa: BLE001 - shown to the user, never swallowed
            QMessageBox.critical(self, "Could not save the metric", str(e))
            return
        self.accept()
