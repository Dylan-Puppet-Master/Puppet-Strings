"""The request editor: one field per request column, a Skedge editor, live validation."""

import re
from datetime import date, datetime

from PySide6.QtCore import QRegularExpression, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app.groups import same_group
from puppet_strings.model import WRITABLE_PRIORITIES, Dataset, Priority, Request
from puppet_strings.names import normalize
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request

KEYWORDS = (
    "REQUEST|PREFER|IF|UNLESS|GAP|TO|DO|DOING|NOT|FREE|DURING|ON|AS_ROLE|FOR|WITH|WITHOUT|IN|"
    "ALL_OF|ANY_[0-9]+_OF|EACH_OF|AT_LEAST|AT_MOST|EXACTLY|CONSECUTIVE|MAXIMIZE|MINIMIZE"
)


class SkedgeHighlighter(QSyntaxHighlighter):
    """Colors keywords, names, strings, dates, durations and comments."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules = [
            (
                QRegularExpression(r"\b(" + KEYWORDS + r")\b"),
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


class SkedgeEdit(QPlainTextEdit):
    """The Skedge text box, which suggests names once a namespace and a dot are typed."""

    PARTIAL_NAME = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z0-9_]*)+$")

    def __init__(self) -> None:
        super().__init__()
        self.setFont(QFont("monospace"))
        self.setTabStopDistance(24)
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.names = QStringListModel([], self.completer)
        self.completer.setModel(self.names)
        self.completer.activated.connect(self._insert_completion)

    def set_names(self, names: list[str]) -> None:
        """The names to suggest, as `namespace.name`. Reuses the model, leaving no garbage."""
        self.names.setStringList(names)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Type as usual, but leave the popup its own keys and suggest after each change."""
        popup_keys = (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab)
        if self.completer.popup().isVisible() and event.key() in popup_keys:
            event.ignore()
            return
        super().keyPressEvent(event)
        self.suggest()

    def suggest(self) -> None:
        """Open, narrow, or close the popup for the name being typed at the cursor."""
        typed = self.toPlainText()[: self.textCursor().position()]
        match = self.PARTIAL_NAME.search(typed)
        popup = self.completer.popup()
        if match is None:
            popup.hide()
            return
        if match.group() != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(match.group())
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        if not self.completer.completionCount():
            popup.hide()
            return
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        self.completer.complete(rect)

    def _insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        typed = len(self.completer.completionPrefix())
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, typed)
        cursor.insertText(completion)
        self.setTextCursor(cursor)


class GroupsEdit(QListWidget):
    """The groups a request is in, as a tick against every group there is."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMaximumHeight(90)
        self.setToolTip("Tick every group this request belongs to")
        self.itemChanged.connect(lambda _: self.changed.emit())

    def show_groups(self, groups: list[str], ticked: tuple[str, ...]) -> None:
        """List every group, with the request's own ticked."""
        self.blockSignals(True)
        self.clear()
        for group in groups:
            item = QListWidgetItem(group)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            inside = any(same_group(group, g) for g in ticked)
            item.setCheckState(Qt.Checked if inside else Qt.Unchecked)
            self.addItem(item)
        self.blockSignals(False)

    def ticked(self) -> tuple[str, ...]:
        """The groups ticked, in the order they are listed."""
        rows = range(self.count())
        return tuple(self.item(r).text() for r in rows if self.item(r).checkState() == Qt.Checked)


class RequestEditor(QWidget):
    """Edits one request. Emits `saved(request, original_id)` and `deleted(request_id)`."""

    saved = Signal(object, object)
    deleted = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
        self.groups: list[str] = []
        self.original_id: str | None = None
        self.id_label = QLabel("")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("what this request is for; the id is made from it")
        self.priority_box = QComboBox()
        self.priority_box.addItems([p.value for p in WRITABLE_PRIORITIES])
        self.weight_box = QDoubleSpinBox()
        self.weight_box.setRange(0.01, 1000)
        self.weight_box.setValue(1)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("comma-separated")
        self.groups_edit = GroupsEdit()
        self.requester_edit = QLineEdit()
        self.requester_edit.setPlaceholderText("who asked for this; a staff name")
        self.requester_names = QStringListModel([], self)
        self.requester_completer = QCompleter(self.requester_names, self)
        self.requester_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.requester_completer.setFilterMode(Qt.MatchContains)
        self.requester_edit.setCompleter(self.requester_completer)
        self.created_label = QLabel("")
        self.skedge_edit = SkedgeEdit()
        self.highlighter = SkedgeHighlighter(self.skedge_edit.document())
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.save_button = QPushButton("Save")
        self.delete_button = QPushButton("Delete")
        self.new_button = QPushButton("New")

        form = QFormLayout()
        form.addRow("id", self.id_label)
        form.addRow("description", self.description_edit)
        form.addRow("priority", self.priority_box)
        form.addRow("weight", self.weight_box)
        form.addRow("tags", self.tags_edit)
        form.addRow("groups", self.groups_edit)
        form.addRow("requester", self.requester_edit)
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
        self.requester_edit.textChanged.connect(self.timer.start)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.new_button.clicked.connect(self.clear)
        self.clear()

    def set_dataset(self, dataset: Dataset | None, groups: list[str] | None = None) -> None:
        """Names are validated and suggested against this dataset; groups fill the checklist."""
        self.dataset = dataset
        self.groups = list(groups or [])
        self.groups_edit.show_groups(self.groups, self.groups_edit.ticked())
        self.requester_names.setStringList(sorted(dataset.staff) if dataset else [])
        names = (
            []
            if dataset is None
            else [
                f"{namespace}.{name}"
                for namespace, rows in name_listing(dataset).items()
                for name, _ in rows
            ]
        )
        self.skedge_edit.set_names(names)
        self.validate()

    def show_request(self, request: Request) -> None:
        """Load a request into the fields."""
        self.original_id = request.id
        self.id_label.setText(request.id)
        self.description_edit.setText(request.description)
        self.priority_box.setCurrentText(request.priority.value)
        self.weight_box.setValue(request.weight)
        self.tags_edit.setText(", ".join(request.tags))
        self.groups_edit.show_groups(self.groups, request.groups)
        self.requester_edit.setText(request.requester)
        self.created_label.setText(request.created.isoformat() if request.created else "")
        self.skedge_edit.setPlainText(request.skedge)
        self.delete_button.setEnabled(True)
        self.validate()

    def clear(self) -> None:
        """Start a new request."""
        self.original_id = None
        self.id_label.setText("(assigned on save)")
        self.description_edit.clear()
        self.priority_box.setCurrentText(Priority.MEDIUM.value)
        self.weight_box.setValue(1)
        self.tags_edit.clear()
        self.groups_edit.show_groups(self.groups, ())
        self.requester_edit.clear()
        self.created_label.setText(date.today().isoformat())
        self.skedge_edit.setPlainText("")
        self.delete_button.setEnabled(False)
        self.validate()

    def current(self) -> Request:
        """The request as the fields describe it."""
        priority = Priority(self.priority_box.currentText())
        created = self.created_label.text()
        return Request(
            id=self.original_id or "",
            description=self.description_edit.text().strip(),
            skedge=self.skedge_edit.toPlainText(),
            priority=priority,
            weight=1.0 if priority.hard else self.weight_box.value(),
            tags=tuple(t.strip() for t in self.tags_edit.text().split(",") if t.strip()),
            groups=self.groups_edit.ticked(),
            requester=normalize(self.requester_edit.text()),
            created=date.fromisoformat(created) if created else None,
        )

    def validate(self) -> bool:
        """Validate the fields; show the result under the editor."""
        if self.dataset is None:
            return self._report("No data loaded", ok=False)
        request = self.current()
        try:
            copies = validate_request(request, self.dataset)
        except SkedgeError as e:
            return self._report(str(e), ok=False)
        keys = {c.key for c in copies if c.key}
        return self._report(f"Valid ({len(keys)} EACH_OF copies)" if keys else "Valid", ok=True)

    def insert_name(self, text: str) -> None:
        """Insert a name at the cursor (from the names panel)."""
        self.skedge_edit.insertPlainText(text)
        self.skedge_edit.setFocus()

    # what the line under the editor says, and what it means: valid, broken, or in hand
    COLORS = {True: "color: #1b6f3b", False: "color: #b00020", None: "color: #6b6b6b"}

    def _report(self, message: str, ok: bool | None) -> bool:
        """Say how the request stands. `ok` of None is neither: a note, with Save left alone."""
        self.status.setText(message)
        self.status.setStyleSheet(self.COLORS[ok])
        if ok is not None:
            self.save_button.setEnabled(ok)
        return bool(ok)

    def _priority_changed(self, text: str) -> None:
        self.weight_box.setEnabled(not Priority(text).hard)
        self.timer.start()

    def saving(self) -> None:
        """Say that the write is under way; the sheet is not always quick."""
        self.save_button.setEnabled(False)
        self.save_button.setText("Saving…")
        self._report("Saving…", ok=None)
        QApplication.processEvents()  # so the button changes before the write, not after

    def saved_as(self, request: Request, note: str = "") -> None:
        """Show the id the store gave the request just saved, and that it is written.

        The confirmation names the time, so a second save of the same request still shows
        that something happened, and stays until the next edit re-validates the request.
        """
        self.original_id = request.id
        self.id_label.setText(request.id)
        self.delete_button.setEnabled(True)
        self.save_button.setText("Save")
        self._report(f"✓ Saved {request.id} at {datetime.now():%H:%M:%S}{note}", ok=True)

    def not_saved(self, why: str) -> None:
        """Put the editor back the way it was, the save having been called off.

        The request is still whatever it was, so Save goes back to being the way to save it.
        """
        self.save_button.setText("Save")
        self.save_button.setEnabled(True)
        self._report(why, ok=None)

    def _save(self) -> None:
        if not self.validate():
            return
        self.saving()
        self.saved.emit(self.current(), self.original_id)

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
