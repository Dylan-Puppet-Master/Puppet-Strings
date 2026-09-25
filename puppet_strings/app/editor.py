"""The request editor: one field per request column, a Skedge editor, live validation."""

import re
from dataclasses import replace
from datetime import date, datetime

from PySide6.QtCore import QModelIndex, QRegularExpression, QStringListModel, Qt, Signal
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
from puppet_strings.app.facets import named_dates, written_dates
from puppet_strings.model import SCOPES, WRITABLE_PRIORITIES, Dataset, Priority, Request, Scope
from puppet_strings.names import normalize
from puppet_strings.requests_db import DEFAULT_SCOPE, describe
from puppet_strings.skedge.ast import NoSession, SkedgeError
from puppet_strings.skedge.namespaces import NAMESPACES, written
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request

# a dotted name, or a namespace on its own
NAME_PATTERN = r"\b(?:[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+|(?:" + "|".join(NAMESPACES) + r")\b)"

KEYWORD_WORDS = (
    "REQUEST",
    "PREFER",
    "EXCLUDE",
    "IF",
    "UNLESS",
    "THEN",
    "AND",
    "OR",
    "GAP",
    "TO",
    "DO",
    "NOT",
    "FREE",
    "BUSY",
    "DURING",
    "ON",
    "AS_ROLE",
    "FOR",
    "WITH",
    "WITHOUT",
    "IN",
    "ALL",
    "EACH",
    "ANY",
    "AT_LEAST",
    "AT_MOST",
    "EXACTLY",
    "CONSECUTIVE",
    "MAXIMIZE",
    "MINIMIZE",
)
KEYWORDS = "|".join(KEYWORD_WORDS)


def is_keyword(word: str) -> bool:
    """Whether a word is a Skedge keyword, in whichever case it is written."""
    return word.upper() in KEYWORD_WORDS


class SkedgeHighlighter(QSyntaxHighlighter):
    """Colors keywords, names, strings, dates, durations and comments.

    Keywords are coloured in whichever case they are written in, because Skedge reads them
    in whichever case they are written in: a request typed in lower case is a request, and
    a box that only colours the shouted version says otherwise.
    """

    def __init__(self, document, colours=palette) -> None:
        """`colours` is a module of colour names laid out like `app.palette`."""
        super().__init__(document)
        keywords = QRegularExpression(r"\b(" + KEYWORDS + r")\b")
        keywords.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
        self.rules = [
            (keywords, _format(colours.KEYWORD, bold=True)),
            (QRegularExpression(NAME_PATTERN), _format(colours.NAME)),
            (QRegularExpression(r"'[^']*'"), _format(colours.STRING)),
            (
                QRegularExpression(r"\b\d{4}-\d{2}-\d{2}\b|\b\d+(\.\d+)?[mhd]\b"),
                _format(colours.NUMBER),
            ),
            (QRegularExpression(r"#[^\n]*"), _format(colours.COMMENT, italic=True)),
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
    """

    save_requested = Signal()  # Ctrl+S, which the popup would otherwise swallow

    # \Z rather than $, which also matches before a newline and so reads past a line's end
    PARTIAL_NAME = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z0-9_]*)*\Z")
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
        self.whole: set[str] = set()  # names, namespaces and branches, each finished as typed

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Suggest every name the dataset has, or none without one.

        Shorter names first, since a match is on any part of a name: `clinic_3` is
        `blocks.clinic_3` far more often than one of the day's offerings in it.
        """
        listing = name_listing(dataset).items() if dataset is not None else ()
        names = [written(ns, name) for ns, rows in listing for name, _ in rows]
        self.set_names(sorted(names, key=lambda n: n.count(".")))

    def set_names(self, names: list[str]) -> None:
        """The names to suggest, as `namespace.name`. Reuses the model, leaving no garbage."""
        parts = (n.split(".") for n in names)
        self.whole = {".".join(p[:i]) for p in parts for i in range(1, len(p) + 1)}
        self.names.setStringList(names)
        self.completer.setCompletionPrefix("")  # the old prefix was narrowing the old list

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Type as usual, but leave the popup its own keys and suggest after each edit.

        Ctrl+S is asked for here rather than left to the editor around this box: with the
        popup open, the completer hands its keys straight to this box and nowhere else.
        """
        popup = self.completer.popup()
        if event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            popup.hide()
            self.save_requested.emit()
            return
        if (
            popup.isVisible()
            and event.key() in (Qt.Key_Enter, Qt.Key_Return)
            and not popup.currentIndex().isValid()
        ):
            popup.hide()  # nothing picked, so Enter is a new line; the completer sees it taken
        popup_keys = (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab)
        if popup.isVisible() and event.key() in popup_keys:
            event.ignore()
            return
        before = self.document().revision()
        super().keyPressEvent(event)
        if self.document().revision() != before:
            self.suggest()
        else:
            self.completer.popup().hide()  # the cursor moved; nothing is being typed

    def suggest(self) -> None:
        """Open, narrow, or close the popup for the name being typed at the cursor."""
        typed = self.toPlainText()[: self.textCursor().position()]
        match = self.PARTIAL_NAME.search(typed)
        popup = self.completer.popup()
        if match is None or not self._worth_offering(match.group()):
            popup.hide()
            return
        if match.group() != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(match.group())
            # A name or namespace already written in full picks nothing, so Enter ends the
            # line there; Down picks the first suggestion.
            first = self.completer.completionModel().index(0, 0)
            popup.setCurrentIndex(QModelIndex() if match.group() in self.whole else first)
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
        # The days it is read on: this session's, unless it is the day's, the week's or the
        # season's business.
        self.scope_box = QComboBox()
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
        self.skedge_edit.save_requested.connect(self._save)
        self.highlighter = SkedgeHighlighter(self.skedge_edit.document())
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.save_button = QPushButton("Save")
        self.delete_button = QPushButton("Delete")
        self.new_button = QPushButton("New")
        self._lay_out()

        # Nothing is checked as it is typed, or when it is opened: half a Skedge is always
        # wrong, and saying so was more noise than help. It is checked when saved, and saved
        # whatever the check finds, with the line under the editor saying what that was;
        # a request that does not validate is left out of solving until it is fixed.
        self.priority_box.currentTextChanged.connect(self._priority_changed)
        self.checked: dict[Request, object] = {}  # see `_validated`
        self.checked_for: Dataset | None = None
        # The scope follows the dates the Skedge's ON names as it is written, unless it has
        # been picked by hand for this request. Opening a request leaves its scope alone.
        self.follow_on = False  # the Skedge was edited since the last check
        self.scope_picked = False
        self.skedge_edit.textChanged.connect(self._skedge_edited)
        self.scope_box.activated.connect(self._scope_picked)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.new_button.clicked.connect(self.new_requested.emit)
        self.clear()

    def _lay_out(self) -> None:
        """Put the fields in a column: the form, the Skedge box under it, the buttons last.

        On its own so the canvas's card, which has the same fields, can arrange them its way.
        """
        form = QFormLayout()
        form.addRow("id", self.id_label)
        form.addRow("description", self.description_edit)
        form.addRow("priority", self.priority_box)
        form.addRow("weight", self.weight_box)
        form.addRow("tags", self.tags_edit)
        form.addRow("scope", self.scope_box)
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

    def set_dataset(self, dataset: Dataset | None, groups: list[str] | None = None) -> None:
        """Names are validated and suggested against this dataset.

        A scope that was the old day's own — its week, its session — becomes the new day's
        of the same kind. One about other dates, a request's own or one its ON called for,
        stays as it is: the same day loaded again after a save must not move it.
        """
        was, self.dataset = self.dataset, dataset
        chosen = self.scope_box.currentData()
        own = chosen is not None and was is not None and chosen == was.scope(chosen.kind)
        self._offer_scopes(chosen.kind if own else chosen)
        self.groups = list(groups or [])
        self.requester_names.setStringList(sorted(dataset.staff) if dataset else [])
        self.skedge_edit.set_dataset(dataset)

    def _offer_scopes(self, keep: Scope | str | None = None) -> None:
        """Offer the day, week, session and season of the date being scheduled.

        `keep` is a scope to choose, or a kind to choose the date's own of. A request's
        own scope is always on offer, so opening one whose week has been redrawn since, say,
        does not quietly propose moving it.
        """
        box = self.scope_box
        box.blockSignals(True)
        box.clear()
        if self.dataset is not None:
            offered = [self.dataset.scope(kind) for kind in SCOPES]
            if isinstance(keep, Scope) and keep not in offered:
                offered.append(keep)
            for scope in offered:
                box.addItem(describe(scope), scope)
            wanted = keep if isinstance(keep, Scope) else self.dataset.scope(keep or DEFAULT_SCOPE)
            box.setCurrentIndex(offered.index(wanted))  # findData cannot compare a Scope
        elif isinstance(keep, Scope):  # no date loaded, but a request still has its own
            box.addItem(describe(keep), keep)
        box.blockSignals(False)

    def show_request(self, request: Request) -> None:
        """Load a request into the fields."""
        self._offer_scopes(request.scope)
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
        self._shown()

    def show_group(self, group: str) -> None:
        """Say which shelf the request is on, or that it is on none."""
        self.group = group
        self.group_label.setText(group or "none — drag the row onto a group to move it")

    def clear(self, group: str = "", scope: str = "") -> None:
        """Start a new request, on the group being shown and with that group's own scope.

        `scope` is the kind the group's requests take when it says; without it a request is
        scoped to this session, which is where a request asked for this session belongs.
        """
        self.show_group(group)
        self._offer_scopes(scope)
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
        self._shown()

    def _shown(self) -> None:
        """A request was just put in the fields: nothing is said about it until it is saved."""
        self.follow_on = self.scope_picked = False  # and it keeps its scope until then
        self._report("", ok=None)

    def _skedge_edited(self) -> None:
        self.follow_on = True

    def _scope_picked(self) -> None:
        """A scope chosen by hand stays, whatever the ON says; saving says if it misses."""
        self.scope_picked = True

    def _follow(self, days) -> str:
        """Scope the request to the narrowest scope holding the ON's dates; say if it moved."""
        fit = self.dataset.fitting_scope(days)
        if fit is None or fit == self.scope_box.currentData():
            return ""
        self._offer_scopes(fit)
        return f"; scope set to {describe(fit)} for its ON"

    def show_scope(self, scope: Scope) -> None:
        """Choose a scope, as the window does when it is asked to fix one on saving."""
        self._offer_scopes(scope)

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
            scope=self.scope_box.currentData(),
        )

    def validate(self) -> bool:
        """Validate the fields; show the result under the editor."""
        if self.dataset is None:
            return self._report("No data loaded", ok=False)
        request = self.current()
        try:
            copies = self._validated(request)
        except NoSession as e:  # right on a session's dates, so it can still be saved
            self._report(str(e), ok=None)
            return True
        except SkedgeError as e:
            return self._report(str(e), ok=False)
        keys = {c.key for c in copies if c.key}
        days = named_dates(request, self.dataset, copies)
        note = self._follow(days) if self.follow_on and not self.scope_picked else ""
        self.follow_on = False
        scope = self.scope_box.currentData()
        missed = [d for d in days if scope is not None and not scope.covers(d)]
        if missed:
            self._report(
                f"Its scope, {describe(scope)}, is not read on {written_dates(missed)}; "
                "saving will offer one that is",
                ok=None,
            )
            return True
        valid = f"Valid ({len(keys)} EACH copies)" if keys else "Valid"
        return self._report(valid + note, ok=True)

    def _validated(self, request: Request) -> tuple:
        """`validate_request`, remembered for the day loaded.

        A request opened again, or typed back to how it was, is not resolved again. Its id
        plays no part in it.
        """
        if self.checked_for is not self.dataset or len(self.checked) > 1000:
            self.checked, self.checked_for = {}, self.dataset
        key = replace(request, id="")
        if key not in self.checked:
            try:
                self.checked[key] = validate_request(request, self.dataset)
            except SkedgeError as e:
                self.checked[key] = e
        found = self.checked[key]
        if isinstance(found, SkedgeError):
            raise found.with_traceback(None)
        return found

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
        """Say how the request stands. `ok` of None is neither: a note."""
        self.status.setText(message)
        self.status.setStyleSheet(self.COLORS[ok])
        return bool(ok)

    def _priority_changed(self, text: str) -> None:
        self.weight_box.setEnabled(not Priority(text).hard)

    def saving(self) -> None:
        """Say that the write is under way; the sheet is not always quick."""
        self.save_button.setEnabled(False)
        self.save_button.setText("Saving…")
        self._report("Saving…", ok=None)
        QApplication.processEvents()  # so the button changes before the write, not after

    def saved_as(self, request: Request, note: str = "", problem: str = "") -> None:
        """Show the id the store gave the request just saved, and that it is written.

        The confirmation names the time, so a second save of the same request still shows
        that something happened, and stays until the request is next saved or opened.
        `problem` is what is wrong with it, if it does not validate: it is saved all the
        same, and said in red.
        """
        self.original_id = request.id
        self.id_label.setText(request.id)
        self.delete_button.setEnabled(True)
        self.save_button.setText("Save")
        self.save_button.setEnabled(True)
        saved = f"✓ Saved {request.id} at {datetime.now():%H:%M:%S}{note}"
        self._report(f"{saved}. {problem}" if problem else saved, ok=not problem)

    def not_saved(self, why: str) -> None:
        """Put the editor back the way it was, the save having been called off.

        The request is still whatever it was, so Save goes back to being the way to save it.
        """
        self.save_button.setText("Save")
        self.save_button.setEnabled(True)
        self._report(why, ok=None)

    def _save(self) -> None:
        """Save the request, whether it validates or not; see `saved_as`."""
        if self.dataset is None:
            self._report("No data loaded", ok=False)
            return
        self.validate()  # which is when the scope follows the ON
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
