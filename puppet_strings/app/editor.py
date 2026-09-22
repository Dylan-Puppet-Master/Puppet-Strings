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
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app import palette
from puppet_strings.model import WRITABLE_PRIORITIES, Dataset, Priority, Request
from puppet_strings.names import normalize
from puppet_strings.sheets.requests import request_tabs, special_tab
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request

KEYWORD_WORDS = (
    "REQUEST",
    "PREFER",
    "IF",
    "UNLESS",
    "GAP",
    "TO",
    "DO",
    "NOT",
    "FREE",
    "DURING",
    "ON",
    "AS_ROLE",
    "FOR",
    "WITH",
    "WITHOUT",
    "IN",
    "ALL_OF",
    "EACH_OF",
    "AT_LEAST",
    "AT_MOST",
    "EXACTLY",
    "CONSECUTIVE",
    "MAXIMIZE",
    "MINIMIZE",
)
ANY_N_OF = r"ANY_[0-9]+_OF"
KEYWORDS = "|".join((*KEYWORD_WORDS, ANY_N_OF))


def is_keyword(word: str) -> bool:
    """Whether a word is a Skedge keyword, in whichever case it is written."""
    shouted = word.upper()
    return shouted in KEYWORD_WORDS or re.fullmatch(ANY_N_OF, shouted) is not None


class SkedgeHighlighter(QSyntaxHighlighter):
    """Colors keywords, names, strings, dates, durations and comments.

    Keywords are coloured in whichever case they are written in, because Skedge reads them
    in whichever case they are written in: a request typed in lower case is a request, and
    a box that only colours the shouted version says otherwise.
    """

    def __init__(self, document) -> None:
        super().__init__(document)
        keywords = QRegularExpression(r"\b(" + KEYWORDS + r")\b")
        keywords.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
        self.rules = [
            (keywords, _format(palette.KEYWORD, bold=True)),
            (QRegularExpression(r"\b[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+"), _format(palette.NAME)),
            (QRegularExpression(r"'[^']*'"), _format(palette.STRING)),
            (
                QRegularExpression(r"\b\d{4}-\d{2}-\d{2}\b|\b\d+(\.\d+)?[mhd]\b"),
                _format(palette.NUMBER),
            ),
            (QRegularExpression(r"#[^\n]*"), _format(palette.COMMENT, italic=True)),
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
    """The Skedge text box, which suggests the names that match what is being typed.

    Typing `dylan` offers `staff.dylan`: the namespace is part of the name, but it is not
    what anybody has in mind when they go looking for somebody, and typing `staff.` first
    to find out how a name is spelled is a thing to remember rather than a help.

    The dates are the exception, and are only suggested once `dates.` has been typed. A
    date is written as a date most of the time, the calendar pane beside the box is how one
    is picked, and a bare word offering half the season buries the name being looked for.
    """

    PARTIAL_NAME = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z0-9_]*)*$")
    DATES = "dates."
    SHORTEST = 2  # letters before a bare word suggests anything; one letter is every name

    def __init__(self) -> None:
        super().__init__()
        self.setFont(QFont("monospace"))
        self.setTabStopDistance(24)
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        # A name is suggested by any part of it, so `dylan` finds `staff.dylan` and
        # `riflery` finds `activities.clinics.riflery`.
        self.completer.setFilterMode(Qt.MatchContains)
        self.names = QStringListModel([], self.completer)
        self.completer.setModel(self.names)
        self.completer.activated.connect(self._insert_completion)
        self.every: list[str] = []
        self.but_dates: list[str] = []
        self.showing: list[str] | None = None

    def set_names(self, names: list[str]) -> None:
        """The names to suggest, as `namespace.name`. Reuses the model, leaving no garbage."""
        self.every = list(names)
        self.but_dates = [n for n in self.every if not n.startswith(self.DATES)]
        self.showing = None
        self.names.setStringList(self.every)

    def _offer(self, names: list[str]) -> None:
        """Put a list in the completer's model, if it is not the one already there."""
        if self.showing is names:
            return
        self.showing = names
        self.names.setStringList(names)
        self.completer.setCompletionPrefix("")  # the old prefix was narrowing the old list

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
        if match is None or not self._worth_offering(match.group()):
            popup.hide()
            return
        self._offer(self.every if "." in match.group() else self.but_dates)
        if match.group() != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(match.group())
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        if not self.completer.completionCount():
            popup.hide()
            return
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        self.completer.complete(rect)

    def _worth_offering(self, fragment: str) -> bool:
        """Whether a fragment is one to look names up by.

        A namespace and a dot always are. A bare word has to be long enough to narrow
        anything down, and must not be a keyword: `do` is a word being written, not a
        search for every name with `do` in it.
        """
        if "." in fragment:
            return True
        return len(fragment) >= self.SHORTEST and not is_keyword(fragment)

    def _insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        typed = len(self.completer.completionPrefix())
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, typed)
        cursor.insertText(completion)
        self.setTextCursor(cursor)


class RequestEditor(QWidget):
    """Edits one request. Emits `saved(request, original_id)` and `deleted(request_id)`."""

    saved = Signal(object, object)
    deleted = Signal(str)
    new_requested = Signal()  # the window knows which group a new request joins

    def __init__(self) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
        self.groups: list[str] = []
        self.original_id: str | None = None
        self.id_label = QLabel("")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("what this request is for")
        self.priority_box = QComboBox()
        self.priority_box.addItems([p.value for p in WRITABLE_PRIORITIES])
        self.weight_box = QDoubleSpinBox()
        self.weight_box.setRange(0.01, 1000)
        self.weight_box.setValue(1)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("comma-separated")
        # Which tab of the Requests sheet it is written on, which is also which loads read
        # it: this span's Special tab unless it is something that holds all season.
        self.home_box = QComboBox()
        # The shelf the request sits on. It is shown, not chosen: a new request joins the
        # group the pane is on, and an existing one is moved by dragging its row onto
        # another group's label, which is one way of doing it rather than two.
        self.group_label = QLabel("")
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
        form.addRow("on tab", self.home_box)
        form.addRow("group", self.group_label)
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
        self.new_button.clicked.connect(self.new_requested.emit)
        self.clear()

    def set_dataset(self, dataset: Dataset | None, groups: list[str] | None = None) -> None:
        """Names are validated and suggested against this dataset."""
        self.dataset = dataset
        self._fill_homes(request_tabs(dataset.this_span) if dataset else ())
        self.groups = list(groups or [])
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

    def _fill_homes(self, tabs: tuple[str, ...], keep: str = "") -> None:
        """Offer the tabs of the span being scheduled, plus whichever one `keep` names.

        A request read from another span's tab — one looked at after the date was moved —
        keeps its own tab in the list, so opening it does not quietly propose moving it.
        """
        chosen = keep or self.home_box.currentText()
        if not chosen and self.dataset is not None:
            chosen = special_tab(self.dataset.this_span)
        self.home_box.blockSignals(True)
        self.home_box.clear()
        extra = [chosen] if chosen and chosen not in tabs else []
        self.home_box.addItems(list(tabs) + extra)
        self.home_box.setCurrentText(chosen)
        self.home_box.blockSignals(False)

    def show_request(self, request: Request) -> None:
        """Load a request into the fields."""
        self._fill_homes(request_tabs(self.dataset.this_span) if self.dataset else (), request.home)
        self.original_id = request.id
        self.id_label.setText(request.id)
        self.description_edit.setText(request.description)
        self.priority_box.setCurrentText(request.priority.value)
        self.weight_box.setValue(request.weight)
        self.tags_edit.setText(", ".join(request.tags))
        self.show_group(request.group)
        self.requester_edit.setText(request.requester)
        self.created_label.setText(request.created.isoformat() if request.created else "")
        self.skedge_edit.setPlainText(request.skedge)
        self.delete_button.setEnabled(True)
        self.validate()

    def show_group(self, group: str) -> None:
        """Say which shelf the request is on, or that it is on none."""
        self.group = group
        self.group_label.setText(group or "none — drag the row onto a group to move it")

    def clear(self, group: str = "", home: str = "") -> None:
        """Start a new request, on the group being shown and that group's own tab.

        `home` is the group's default tab when it has one; without it the request goes to
        this span's Special tab, which is where a request asked for this session belongs.
        """
        self.show_group(group)
        self._fill_homes(request_tabs(self.dataset.this_span) if self.dataset else (), home)
        if self.dataset is not None and not home:
            self.home_box.setCurrentText(special_tab(self.dataset.this_span))
        self.original_id = None
        self.id_label.setText("(assigned on save)")
        self.description_edit.clear()
        self.priority_box.setCurrentText(Priority.MEDIUM.value)
        self.weight_box.setValue(1)
        self.tags_edit.clear()
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
            group=self.group,
            requester=normalize(self.requester_edit.text()),
            created=date.fromisoformat(created) if created else None,
            home=self.home_box.currentText(),
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
    COLORS = {
        True: f"color: {palette.GOOD}",
        False: f"color: {palette.BAD}",
        None: f"color: {palette.QUIET}",
    }

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
            self.new_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Ctrl+S saves."""
        if event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self._save()
            return
        super().keyPressEvent(event)
