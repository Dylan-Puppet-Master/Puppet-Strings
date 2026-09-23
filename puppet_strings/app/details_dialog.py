"""The popups a name in the Namespaces pane opens: what it stands for, and mapping tables.

A mapping is the one name worth changing rather than reading, so its popup is the table
itself, editable, written straight back to its tab. Everything else is a reading: who is in
a category, what an activity asks for, what the cabin act board wrote on a card.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from puppet_strings.app.details import Details
from puppet_strings.config import Config
from puppet_strings.model import is_numeric
from puppet_strings.sheets.mappings import INDEX_COLUMNS, TAB_PREFIX, key_columns
from puppet_strings.sheets.source import Source, split_list

CONFIG_SHEET = "config"
SPARE_ROWS = 5  # blank rows at the bottom of a mapping table, to add rows without ceremony


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


class MappingDialog(QDialog):
    """One mapping's rows, as they are on its tab, editable.

    The tab is read again rather than rebuilt from the loaded mapping: the sheet holds names
    and the loaded mapping holds identifiers, and showing what is written is the only way to
    edit it and put it back unchanged apart from the edit.
    """

    def __init__(self, source: Source, config: Config, mapping: str, parent=None) -> None:
        super().__init__(parent)
        self.source, self.config, self.mapping = source, config, mapping
        self.tab = f"{TAB_PREFIX}{mapping}"
        self.setWindowTitle(f"mappings.{mapping}")
        self.resize(620, 560)
        self.index = self.source.read(CONFIG_SHEET, config.tabs["mappings"])
        row = self._index_row()
        self.numeric = is_numeric(row.get("value", ""))
        self.default = self._default_box(row)
        table = self.source.read(CONFIG_SHEET, self.tab)
        self.header = table[0] if table else []
        body = table[1:]
        self.grid = QTableWidget(len(body) + SPARE_ROWS, max(len(self.header), 1))
        self.grid.setHorizontalHeaderLabels(_labels(self.header, row))
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, cells in enumerate(body):
            for c in range(len(self.header)):
                self.grid.setItem(r, c, QTableWidgetItem(cells[c] if c < len(cells) else ""))
        for r in range(len(body), len(body) + SPARE_ROWS):
            for c in range(len(self.header)):
                self.grid.setItem(r, c, QTableWidgetItem(""))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("When nothing is written down", self.default)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>mappings.{mapping}</b><br>{self.tab}, on the config sheet"))
        layout.addWidget(self.grid)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _default_box(self, row: dict[str, str]) -> QDoubleSpinBox | QLineEdit:
        """A number held between the ends of its scale, or a Skedge phrase to stand in."""
        if not self.numeric:
            box = QLineEdit(row.get("default", ""))
            box.setPlaceholderText("no default: every key needs a row")
            box.setToolTip(
                f"What a key with no row gives, from {row.get('value', '')}: a name, or "
                "a phrase such as ANY 1 {staff.office}"
            )
            return box
        low, high = (_number(row.get(name)) for name in ("scale_min", "scale_max"))
        box = QDoubleSpinBox()
        box.setDecimals(2)
        box.setRange(low, high)
        box.setToolTip(f"What a key with no row is worth, between {low:g} and {high:g}")
        box.setValue(_number(row.get("default")) if row.get("default") else low)
        return box

    def default_text(self) -> str:
        """The default as it is written back to the Mappings tab."""
        if self.numeric:
            return _trim(self.default.value())
        return self.default.text().strip()

    def _index_row(self) -> dict[str, str]:
        """The row on the Mappings index tab for this mapping, as a dict."""
        header = [c.strip() for c in self.index[0]] if self.index else []
        for cells in self.index[1:]:
            row = dict(zip(header, [*cells, *[""] * len(header)], strict=False))
            if row.get("mapping", "").strip() == self.mapping:
                return row
        return {}

    def index_rows(self) -> list[list[str]]:
        """The Mappings index tab with this mapping's default as the box now says.

        A mapping declared with no `default` column gets one, because a default it cannot be
        given is no better than no box at all.
        """
        header = [c.strip() for c in self.index[0]] if self.index else list(INDEX_COLUMNS)
        if "default" not in header:
            header = [*header, "default"]
        written = [header]
        for cells in self.index[1:]:
            row = [*cells, *[""] * (len(header) - len(cells))][: len(header)]
            if row[header.index("mapping")].strip() == self.mapping:
                row[header.index("default")] = self.default_text()
            written.append(row)
        return written

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
        """Write the rows and the default back, and say so rather than closing quietly."""
        try:
            self.source.write(CONFIG_SHEET, self.tab, self.rows())
            self.source.write(CONFIG_SHEET, self.config.tabs["mappings"], self.index_rows())
        except Exception as e:  # noqa: BLE001 - shown to the user, never swallowed
            QMessageBox.critical(self, "Could not save the mapping", str(e))
            return
        self.accept()


def _labels(header: list[str], row: dict[str, str]) -> list[str]:
    """Column headings that say what each key column holds: `key1: staff.counselor`."""
    keys = split_list(row.get("keys", ""))
    sets = dict(zip(key_columns(len(keys)), keys, strict=True))
    shown = []
    for column in header:
        name = column.strip()
        if name in sets:
            shown.append(f"{name}: {sets[name]}")
        elif name == "value" and row.get("value"):
            shown.append(f"value: {row['value']}")
        else:
            shown.append(name)
    return shown


def _number(text: str | None) -> float:
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def _trim(value: float) -> str:
    """A number as a sheet would write it: 3 rather than 3.0."""
    return str(int(value)) if value == int(value) else str(value)
