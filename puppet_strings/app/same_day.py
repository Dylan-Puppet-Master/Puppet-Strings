"""Recording what changed about people today: who is off, and whose RAL has dropped."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from puppet_strings.app.store import RequestStore
from puppet_strings.model import MAX_RAL

NOT_WORKING = "Not working today"
LOWER_RAL = "Lower RAL today"


class SameDayDialog(QDialog):
    """Add or remove today's adjustments. Each change writes the Adjustments tab."""

    def __init__(self, store: RequestStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(f"Today's changes: {store.dataset.target}")
        self.resize(560, 420)

        self._changed = False
        self.staff_box = QComboBox()
        for staff_id in sorted(store.dataset.staff, key=lambda i: store.dataset.staff[i].name):
            self.staff_box.addItem(store.dataset.staff[staff_id].name, staff_id)
        self.change_box = QComboBox()
        self.change_box.addItems([NOT_WORKING, LOWER_RAL])
        self.ral_box = QSpinBox()
        self.ral_box.setRange(1, MAX_RAL)
        self.ral_box.setValue(MAX_RAL - 1)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("why, for the record: sick, short sleep")
        self.apply_button = QPushButton("Apply")
        self.remove_button = QPushButton("Put back to usual")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Staff", "Today", "Note"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        form = QFormLayout()
        form.addRow("staff", self.staff_box)
        form.addRow("change", self.change_box)
        form.addRow("RAL", self.ral_box)
        form.addRow("note", self.note_edit)
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.remove_button)
        closer = QDialogButtonBox(QDialogButtonBox.Close)
        closer.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("In effect today"))
        layout.addWidget(self.table)
        layout.addWidget(closer)

        self.change_box.currentTextChanged.connect(self._change_chosen)
        self.apply_button.clicked.connect(self._apply)
        self.remove_button.clicked.connect(self._remove)
        self.table.itemSelectionChanged.connect(self._row_chosen)
        self._change_chosen(self.change_box.currentText())
        self.show_adjustments()

    @property
    def changed(self) -> bool:
        """Whether anything was written, so the window knows to reload."""
        return self._changed

    def show_adjustments(self) -> None:
        """Fill the table from what is in effect today."""
        today = self.store.dataset.today_adjustments
        self.table.setRowCount(len(today))
        for row, adjustment in enumerate(today):
            name = self.store.dataset.staff[adjustment.staff].name
            standing = NOT_WORKING if not adjustment.available else f"RAL {adjustment.ral}"
            for column, text in enumerate((name, standing, adjustment.note)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.remove_button.setEnabled(bool(today))

    def _change_chosen(self, text: str) -> None:
        self.ral_box.setEnabled(text == LOWER_RAL)

    def _row_chosen(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return
        adjustment = self.store.dataset.today_adjustments[min(rows)]
        self.staff_box.setCurrentText(self.store.dataset.staff[adjustment.staff].name)

    def _apply(self) -> None:
        lower = self.change_box.currentText() == LOWER_RAL
        self.store.set_adjustment(
            self.staff_box.currentData(),
            available=lower,
            ral=self.ral_box.value() if lower else None,
            note=self.note_edit.text().strip(),
        )
        self._done()

    def _remove(self) -> None:
        self.store.clear_adjustment(self.staff_box.currentData())
        self._done()

    def _done(self) -> None:
        """Stay open so several people can be recorded in one go."""
        self._changed = True
        self.note_edit.clear()
        self.show_adjustments()
