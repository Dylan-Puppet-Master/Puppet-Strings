"""Recording what changed about people today: who is resting, and who is short of sleep."""

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
from puppet_strings.model import MAX_RAL, Rest

SLEEP = "Sleep agreement"
SICKNESS = "Sickness"
SLEEP_PENALTY = 1  # the agreement: too little sleep costs one RAL for the day

RESTING_CHOICES = {
    "Resting all day": Rest.ALL_DAY,
    "Resting this morning": Rest.MORNING,
    "Resting this afternoon": Rest.AFTERNOON,
}


class SameDayDialog(QDialog):
    """Record a sleep agreement or a sickness for today, and undo either.

    `kind` picks which: SLEEP takes a RAL off the day, SICKNESS rests someone through all
    of it or half. Both show what is already in effect, since they write the same rows.
    """

    def __init__(self, store: RequestStore, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.kind = kind
        self.setWindowTitle(f"{kind}: {store.dataset.target}")
        self.resize(560, 420)

        self._changed = False
        self.staff_box = QComboBox()
        for staff_id in sorted(store.dataset.staff, key=lambda i: store.dataset.staff[i].name):
            self.staff_box.addItem(store.dataset.staff[staff_id].name, staff_id)
        self.resting_box = QComboBox()
        self.resting_box.addItems(RESTING_CHOICES)
        self.penalty_box = QSpinBox()
        self.penalty_box.setRange(1, MAX_RAL)
        self.penalty_box.setValue(SLEEP_PENALTY)
        self.penalty_box.setPrefix("down ")
        self.penalty_box.setSuffix(" RAL for the day")
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("why, for the record: sick, short sleep")
        self.apply_button = QPushButton("Apply")
        self.remove_button = QPushButton("Put back to usual")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Staff", "Today", "Note"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        form = QFormLayout()
        form.addRow("staff", self.staff_box)
        if kind == SLEEP:
            form.addRow("short of sleep", self.penalty_box)
        else:
            form.addRow("resting", self.resting_box)
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

        self.apply_button.clicked.connect(self._apply)
        self.remove_button.clicked.connect(self._remove)
        self.table.itemSelectionChanged.connect(self._row_chosen)
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
            for column, text in enumerate((name, adjustment.summary, adjustment.note)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.remove_button.setEnabled(bool(today))

    def _row_chosen(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return
        adjustment = self.store.dataset.today_adjustments[min(rows)]
        self.staff_box.setCurrentText(self.store.dataset.staff[adjustment.staff].name)
        choices = {rest: text for text, rest in RESTING_CHOICES.items()}
        if adjustment.resting in choices:
            self.resting_box.setCurrentText(choices[adjustment.resting])
        if adjustment.ral_penalty:
            self.penalty_box.setValue(adjustment.ral_penalty)
        self.note_edit.setText(adjustment.note)

    def _apply(self) -> None:
        note = self.note_edit.text().strip()
        if self.kind == SLEEP:
            self.store.set_adjustment(
                self.staff_box.currentData(), penalty=self.penalty_box.value(), note=note
            )
        else:
            resting = RESTING_CHOICES[self.resting_box.currentText()]
            self.store.set_adjustment(self.staff_box.currentData(), resting=resting, note=note)
        self._done()

    def _remove(self) -> None:
        self.store.clear_adjustment(self.staff_box.currentData())
        self._done()

    def _done(self) -> None:
        """Stay open so several people can be recorded in one go."""
        self._changed = True
        self.note_edit.clear()
        self.show_adjustments()
