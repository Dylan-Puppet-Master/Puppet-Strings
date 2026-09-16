"""The request editor: one field per request column, a Skedge editor, live validation."""

from datetime import date

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.model import Dataset, Priority, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.validate import validate_request

KEYWORDS = (
    "ON|DURING|ACROSS|ROLE|TASK|FORBID|PREFER|AVOID|FOR|CONTINUOUS|AS|PER|BEYOND|GAP|"
    "ANY|ALL|EACH|OF|OR|AND|FREE"
)


class SkedgeHighlighter(QSyntaxHighlighter):
    """Colors keywords, names, strings, dates, durations and comments."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules = [
            (
                QRegularExpression(r"\b(" + "|".join(KEYWORDS) + r")\b"),
                _format("#1f4e9c", bold=True),
            ),
            (QRegularExpression(r"\b[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+"), _format("#1b6f3b")),
            (QRegularExpression(r"'[^']*'"), _format("#8a4b08")),
            (QRegularExpression(r"\b\d{4}-\d{2}-\d{2}\b|\b\d+(\.\d+)?[mhd]\b"), _format("#6a2c8f")),
            (QRegularExpression(r"#[^\n]*"), _format("#808080", italic=True)),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        """Apply every rule to one line."""
        for pattern, fmt in self.rules:
            matches = pattern.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


def _format(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    fmt.setFontItalic(italic)
    return fmt


class RequestEditor(QWidget):
    """Edits one request. Emits `saved(request, original_id)` and `deleted(request_id)`."""

    saved = Signal(object, object)
    deleted = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
        self.original_id: str | None = None
        self.id_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.priority_box = QComboBox()
        self.priority_box.addItems([p.value for p in Priority])
        self.weight_box = QDoubleSpinBox()
        self.weight_box.setRange(0.01, 1000)
        self.weight_box.setValue(1)
        self.created_label = QLabel("")
        self.skedge_edit = QPlainTextEdit()
        self.skedge_edit.setFont(QFont("monospace"))
        self.skedge_edit.setTabStopDistance(24)
        self.highlighter = SkedgeHighlighter(self.skedge_edit.document())
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.save_button = QPushButton("Save")
        self.delete_button = QPushButton("Delete")
        self.new_button = QPushButton("New")

        form = QFormLayout()
        form.addRow("id", self.id_edit)
        form.addRow("description", self.description_edit)
        form.addRow("priority", self.priority_box)
        form.addRow("weight", self.weight_box)
        form.addRow("created", self.created_label)
        buttons = QHBoxLayout()
        for button in (self.new_button, self.save_button, self.delete_button):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("skedge"))
        layout.addWidget(self.skedge_edit, stretch=1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.validate)
        self.skedge_edit.textChanged.connect(self.timer.start)
        self.priority_box.currentTextChanged.connect(self._priority_changed)
        self.weight_box.valueChanged.connect(self.timer.start)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.new_button.clicked.connect(self.clear)
        self.clear()

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Names are validated against this dataset."""
        self.dataset = dataset
        self.validate()

    def show_request(self, request: Request) -> None:
        """Load a request into the fields."""
        self.original_id = request.id
        self.id_edit.setText(request.id)
        self.description_edit.setText(request.description)
        self.priority_box.setCurrentText(request.priority.value)
        self.weight_box.setValue(request.weight)
        self.created_label.setText(request.created.isoformat() if request.created else "")
        self.skedge_edit.setPlainText(request.skedge)
        self.delete_button.setEnabled(True)
        self.validate()

    def clear(self) -> None:
        """Start a new request."""
        self.original_id = None
        self.id_edit.clear()
        self.description_edit.clear()
        self.priority_box.setCurrentText(Priority.MEDIUM.value)
        self.weight_box.setValue(1)
        self.created_label.setText(date.today().isoformat())
        self.skedge_edit.setPlainText("")
        self.delete_button.setEnabled(False)
        self.validate()

    def current(self) -> Request:
        """The request as the fields describe it."""
        priority = Priority(self.priority_box.currentText())
        created = self.created_label.text()
        return Request(
            id=self.id_edit.text().strip(),
            description=self.description_edit.text().strip(),
            skedge=self.skedge_edit.toPlainText(),
            priority=priority,
            weight=1.0 if priority.hard else self.weight_box.value(),
            created=date.fromisoformat(created) if created else None,
        )

    def validate(self) -> bool:
        """Validate the fields; show the result under the editor."""
        if self.dataset is None:
            return self._report("No data loaded", ok=False)
        request = self.current()
        if not request.id:
            return self._report("id is required", ok=False)
        try:
            copies = validate_request(request, self.dataset)
        except SkedgeError as e:
            return self._report(str(e), ok=False)
        keys = {c.key for c in copies if c.key}
        return self._report(f"Valid ({len(keys)} EACH copies)" if keys else "Valid", ok=True)

    def insert_name(self, text: str) -> None:
        """Insert a name at the cursor (from the names panel)."""
        self.skedge_edit.insertPlainText(text)
        self.skedge_edit.setFocus()

    def _report(self, message: str, ok: bool) -> bool:
        self.status.setText(message)
        self.status.setStyleSheet("color: #1b6f3b" if ok else "color: #b00020")
        self.save_button.setEnabled(ok)
        return ok

    def _priority_changed(self, text: str) -> None:
        self.weight_box.setEnabled(not Priority(text).hard)
        self.timer.start()

    def _save(self) -> None:
        if self.validate():
            self.saved.emit(self.current(), self.original_id)
            self.original_id = self.current().id
            self.delete_button.setEnabled(True)

    def _delete(self) -> None:
        if self.original_id:
            self.deleted.emit(self.original_id)
            self.clear()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Ctrl+S saves."""
        if event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self._save()
            return
        super().keyPressEvent(event)
