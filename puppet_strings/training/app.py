"""The trainer's window: `puppet-strings train`.

On the left, the trail of levels and the problems in each, ticked off as they are solved.
In the middle, one problem at a time: what camp is asking for, in plain English, a Skedge
box to answer it in, and what the checker made of the answer. On the right, the same two
panes the request manager has — every name in the session, and the calendar — because
finding the right name is half of writing a request, and the trainee should learn where to
look for one.

Everything here runs on the bundled copy of Session 6 and needs no connection: nothing a
trainee writes goes anywhere near a real schedule.
"""

import random
import sys
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app.calendar_pane import SessionCalendar
from puppet_strings.app.details import details
from puppet_strings.app.details_dialog import DetailsDialog
from puppet_strings.app.editor import SkedgeEdit, SkedgeHighlighter
from puppet_strings.app.namespaces_panel import NamespacesPanel
from puppet_strings.app.worker import Worker
from puppet_strings.model import Dataset, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request
from puppet_strings.training import style
from puppet_strings.training.check import FILLER, Verdict, check_answer
from puppet_strings.training.problems import Level, Problem, load_levels
from puppet_strings.training.progress import Progress, load_progress
from puppet_strings.training.session import dataset

SOLVED, TRIED, NEW = "✓", "●", "○"


def run_training() -> int:
    """Open the trainer and run until it closes."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Skedge Training")
    style.apply(app)
    window = TrainingWindow(load_levels(), load_progress())
    window.show()
    if not window.progress.welcomed:
        QTimer.singleShot(200, window.welcome)
    return app.exec()


class TrainerHighlighter(SkedgeHighlighter):
    """The request manager's Skedge colouring, repainted for a light page."""

    COLOURS = (style.KEYWORD, style.NAME, style.STRING, style.NUMBER, style.COMMENT)

    def __init__(self, document) -> None:
        super().__init__(document)
        # the rules come in the order keyword, name, string, number, comment
        self.rules = [
            (pattern, _format(colour, bold=i == 0, italic=i == 4))
            for i, ((pattern, _), colour) in enumerate(zip(self.rules, self.COLOURS, strict=True))
        ]


def _format(colour: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    fmt.setFontItalic(italic)
    return fmt


class TrainerCalendar(SessionCalendar):
    """The request manager's calendar, shaded for a light page."""

    def __init__(self) -> None:
        super().__init__()
        ink = QTextCharFormat()
        ink.setForeground(QColor(style.INK))
        for weekday in Qt.DayOfWeek:
            self.setWeekdayTextFormat(weekday, ink)

    def show_calendar(self, calendar: dict, target: date | None = None) -> None:
        """Shade the session's days in the trainer's own colour."""
        super().show_calendar(calendar, target)
        camp_day = QTextCharFormat()
        camp_day.setBackground(QColor(style.CAMP_DAY))
        camp_day.setForeground(QColor(style.INK))
        for day in calendar:
            self.setDateTextFormat(QDate(day), camp_day)
        if target is not None:
            today = QTextCharFormat(camp_day)
            today.setFontWeight(QFont.Bold)
            today.setBackground(QColor(style.HIGHLIGHT))
            self.setDateTextFormat(QDate(target), today)


class NamesPane(QWidget):
    """Every name in the session, with a box to find one by any part of it."""

    def __init__(self) -> None:
        super().__init__()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a name")
        self.search.textChanged.connect(self._filter)
        self.tree = NamespacesPanel()
        self.tree.setHeaderLabels(["name", "what it is"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, stretch=1)
        tip = QLabel("Double-click a name to see what it stands for; Enter inserts it.")
        tip.setWordWrap(True)
        tip.setProperty("role", "soft")
        layout.addWidget(tip)

    def show_dataset(self, data: Dataset) -> None:
        """Fill the tree, keeping whatever is being searched for."""
        self.tree.show_dataset(data)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        """Hide every name that does not contain the text, keeping the way down to those that do."""
        text = text.strip().lower()
        items = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            items.append(iterator.value())
            iterator += 1
        for item in items:
            item.setHidden(bool(text))
        if not text:
            for item in items:
                item.setExpanded(False)
            return
        for item in items:
            if text in item.text(0).lower() or text in item.text(1).lower():
                item.setHidden(False)
                parent = item.parent()
                while parent is not None:
                    parent.setHidden(False)
                    parent.setExpanded(True)
                    parent = parent.parent()


class TrainingWindow(QMainWindow):
    """Levels on the left, the problem in the middle, names and calendar on the right."""

    def __init__(self, levels: tuple[Level, ...], progress: Progress) -> None:
        super().__init__()
        self.levels = levels
        self.progress = progress
        self.problems = [p for level in levels for p in level.problems]
        self.level_of = {p.id: level for level in levels for p in level.problems}
        self.items: dict[str, QTreeWidgetItem] = {}
        self.problem: Problem | None = None
        self.data: Dataset | None = None
        self.worker: Worker | None = None
        self.hints_shown = 0
        self.setWindowTitle("Skedge Training")
        self.resize(1440, 900)

        splitter = QSplitter()
        splitter.addWidget(self._trail())
        splitter.addWidget(self._middle())
        splitter.addWidget(self._reference())
        splitter.setSizes([300, 760, 380])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._validate)
        self.editor.textChanged.connect(self._edited)

        start = self.progress.current or self._first_unsolved().id
        self.open_problem(next((p for p in self.problems if p.id == start), self.problems[0]))

    # -- building -------------------------------------------------------------------------

    def _trail(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 14, 6, 14)
        heading = QLabel("Skedge Training")
        heading.setProperty("role", "title")
        layout.addWidget(heading)
        self.score = QLabel()
        self.score.setProperty("role", "soft")
        layout.addWidget(self.score)
        self.bar = QProgressBar()
        self.bar.setMaximum(len(self.problems))
        self.bar.setFixedHeight(10)
        layout.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._picked)
        for number, level in enumerate(self.levels, start=1):
            top = QTreeWidgetItem([f"{number}. {level.name}"])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setToolTip(0, level.blurb)
            self.tree.addTopLevelItem(top)
            for problem in level.problems:
                item = QTreeWidgetItem([problem.title])
                item.setData(0, Qt.UserRole, problem.id)
                top.addChild(item)
                self.items[problem.id] = item
        layout.addWidget(self.tree, stretch=1)
        buttons = QHBoxLayout()
        welcome = QPushButton("About")
        welcome.setProperty("role", "link")
        welcome.clicked.connect(self.welcome)
        reset = QPushButton("Start over")
        reset.setProperty("role", "link")
        reset.clicked.connect(self._reset)
        buttons.addWidget(welcome)
        buttons.addStretch()
        buttons.addWidget(reset)
        layout.addLayout(buttons)
        self._refresh_trail()
        return box

    def _middle(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.level_label = QLabel()
        self.level_label.setProperty("role", "level")
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setWordWrap(True)
        self.sheet_button = QPushButton("Show the cheat sheet")
        self.sheet_button.setProperty("role", "link")
        self.sheet_button.clicked.connect(self._toggle_sheet)
        top = QHBoxLayout()
        top.addWidget(self.level_label)
        top.addStretch()
        top.addWidget(self.sheet_button)
        layout.addLayout(top)
        layout.addWidget(self.title)

        self.sheet = QFrame()
        self.sheet.setProperty("role", "sheet")
        sheet_layout = QVBoxLayout(self.sheet)
        self.blurb = QLabel()
        self.blurb.setWordWrap(True)
        self.teaches = QLabel()
        self.teaches.setFont(QFont("monospace"))
        self.teaches.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.teaches.setWordWrap(True)
        sheet_layout.addWidget(self.blurb)
        sheet_layout.addWidget(self.teaches)
        self.sheet.setVisible(False)
        layout.addWidget(self.sheet)

        who = QLabel("Request")
        who.setProperty("role", "soft")
        layout.addWidget(who)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setProperty("role", "bubble")
        self.prompt.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.prompt)

        chips = QHBoxLayout()
        self.priority_chip = QLabel()
        self.day_chip = QLabel()
        for chip in (self.priority_chip, self.day_chip):
            chip.setProperty("role", "chip")
            chips.addWidget(chip)
        chips.addStretch()
        layout.addLayout(chips)

        self.editor = SkedgeEdit()
        self.highlighter = TrainerHighlighter(self.editor.document())
        self.editor.setPlaceholderText(
            "Write your request here. Start typing a name and pick it from the list."
        )
        self.editor.setMinimumHeight(120)
        self.editor.setMaximumHeight(220)
        layout.addWidget(self.editor)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("Check my answer")
        self.check_button.setProperty("role", "primary")
        self.check_button.clicked.connect(self._check)
        self.hint_button = QPushButton("Hint")
        self.hint_button.clicked.connect(self._hint)
        self.answer_button = QPushButton("Show an answer")
        self.answer_button.clicked.connect(self._reveal)
        self.next_button = QPushButton("Next  →")
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.hint_button)
        buttons.addWidget(self.answer_button)
        buttons.addStretch()
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.feedback = QFrame()
        self.feedback_layout = QVBoxLayout(self.feedback)
        self.feedback_layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(self.feedback)
        self.feedback.setVisible(False)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _reference(self) -> QWidget:
        """The names above the calendar, both in view at once."""
        self.names = NamesPane()
        self.names.tree.picked.connect(self._insert)
        self.names.tree.inspected.connect(self._inspect)
        calendar_page = QWidget()
        calendar_layout = QVBoxLayout(calendar_page)
        calendar_layout.setContentsMargins(0, 8, 0, 0)
        self.calendar = TrainerCalendar()
        self.calendar.setMinimumHeight(280)
        self.calendar.picked.connect(lambda day: self._insert(day.isoformat()))
        self.today_label = QLabel()
        self.today_label.setWordWrap(True)
        tip = QLabel("Shaded days are camp days; bold is dates.target. Click a day to insert it.")
        tip.setWordWrap(True)
        tip.setProperty("role", "soft")
        calendar_layout.addWidget(self.calendar)
        calendar_layout.addWidget(self.today_label)
        calendar_layout.addWidget(tip)
        stack = QSplitter(Qt.Vertical)
        stack.addWidget(self.names)
        stack.addWidget(calendar_page)
        stack.setStretchFactor(0, 1)
        stack.setChildrenCollapsible(False)
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(6, 14, 14, 14)
        layout.addWidget(stack)
        return box

    # -- moving between problems ----------------------------------------------------------

    def open_problem(self, problem: Problem) -> None:
        """Show a problem, with whatever was last written for it."""
        self._keep_draft()
        self.problem = problem
        self.progress.current = problem.id
        self.progress.save()
        self.hints_shown = 0
        level = self.level_of[problem.id]
        number = self.levels.index(level) + 1
        place = level.problems.index(problem) + 1
        self.level_label.setText(
            f"LEVEL {number} · {level.name.upper()} · {place} OF {len(level.problems)}"
        )
        self.title.setText(problem.title)
        self.blurb.setText(level.blurb)
        self.teaches.setText(level.teaches.strip())
        self.prompt.setText(problem.prompt)
        self.priority_chip.setText(f"Priority: {problem.priority.value}")
        self.priority_chip.setToolTip("Given for you: write only the Skedge.")
        self.day_chip.setText(f"Scheduling {problem.day:%A, %B} {problem.day.day}")
        self.day_chip.setToolTip("dates.target — the day being scheduled")
        self._load_day(problem.day)
        attempt = self.progress.of(problem.id)
        self.editor.blockSignals(True)
        self.editor.setPlainText(attempt.draft or problem.starter)
        self.editor.blockSignals(False)
        self.hint_button.setText(f"Hint ({len(problem.hints)})" if problem.hints else "Hint")
        self.hint_button.setEnabled(bool(problem.hints))
        self.feedback.setVisible(False)
        if attempt.solved:
            self._show_solved(attempt.draft or problem.answer, earlier=True)
        self.tree.setCurrentItem(self.items[problem.id])
        self.editor.setFocus()
        self._validate()

    def _load_day(self, day: date) -> None:
        if self.data is not None and self.data.target == day:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.data = dataset(day)
        finally:
            QApplication.restoreOverrideCursor()
        self.names.show_dataset(self.data)
        self.calendar.show_calendar(self.data.calendar, day)
        self.today_label.setText(f"<b>dates.target</b> is {day:%A, %B} {day.day}.")
        self.editor.set_names(
            [f"{ns}.{name}" for ns, rows in name_listing(self.data).items() for name, _ in rows]
        )

    def _picked(self, item: QTreeWidgetItem) -> None:
        problem_id = item.data(0, Qt.UserRole)
        if problem_id:
            self.open_problem(next(p for p in self.problems if p.id == problem_id))
        else:
            item.setExpanded(not item.isExpanded())

    def _next(self) -> None:
        index = self.problems.index(self.problem)
        later = self.problems[index + 1 :] + self.problems[: index + 1]
        after = next((p for p in later if not self.progress.of(p.id).solved), None)
        if after is None:
            QMessageBox.information(self, "Skedge Training", "All problems solved.")
            return
        self.open_problem(after)

    def _first_unsolved(self) -> Problem:
        unsolved = (p for p in self.problems if not self.progress.of(p.id).solved)
        return next(unsolved, self.problems[0])

    def _keep_draft(self) -> None:
        if self.problem is not None:
            self.progress.of(self.problem.id).draft = self.editor.toPlainText()
            self.progress.save()

    # -- writing ---------------------------------------------------------------------------

    def _edited(self) -> None:
        self.timer.start()

    def _validate(self) -> None:
        """Say whether Skedge can read what is written, as it is typed."""
        text = self.editor.toPlainText()
        if not text.strip():
            self._say("", style.SOFT)
            return
        try:
            request = Request("answer", "", text, self.problem.priority)
            validate_request(request, self.data)
        except SkedgeError as e:
            self._say(f"✎  Line {e.line}, column {e.column}: {e.message}", style.BERRY)
            return
        self._say("✓  Valid Skedge", style.LEAF)

    def _say(self, text: str, colour: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};")

    def _insert(self, text: str) -> None:
        self.editor.insertPlainText(text)
        self.editor.setFocus()

    def _inspect(self, name: str) -> None:
        if name.startswith("mappings."):
            MappingView(self.data, name.split(".", 1)[1], self).exec()
            return
        found = details(name, self.data)
        if found is not None:
            DetailsDialog(found, self).exec()

    # -- checking --------------------------------------------------------------------------

    def _check(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip() or self.worker is not None:
            return
        problem = self.problem
        self._keep_draft()
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking…")
        self._feedback("hint", "Checking…", "")
        seed = random.randrange(1 << 16)
        self.worker = Worker(
            lambda: check_answer(text, problem.answer, problem.priority, dataset, problem.day, seed)
        )
        self.worker.done.connect(lambda verdict: self._checked(problem, text, verdict))
        self.worker.failed.connect(self._check_failed)
        self.worker.finished.connect(self._check_finished)
        self.worker.start()

    def _check_finished(self) -> None:
        self.worker = None
        self.check_button.setEnabled(True)
        self.check_button.setText("Check my answer")

    def _check_failed(self, why: str) -> None:
        self._feedback("bad", "Something went wrong checking that", why.splitlines()[-1])

    def _checked(self, problem: Problem, text: str, verdict: Verdict) -> None:
        attempt = self.progress.of(problem.id)
        attempt.tries += 1
        if verdict.correct:
            attempt.solved = True
        self.progress.save()
        self._refresh_trail()
        if problem is not self.problem:
            return  # the trainee moved on while it was checking
        if verdict.correct:
            self._show_solved(text, earlier=False)
            return
        if verdict.error is not None:
            detail = f"Line {verdict.error.line}, column {verdict.error.column}: {verdict.detail}"
            self._feedback("bad", verdict.headline, detail)
            self._move_cursor(verdict.error.line, verdict.error.column)
            return
        self._feedback("bad", verdict.headline, verdict.detail)
        if verdict.schedule or verdict.staff:
            self.feedback_layout.addWidget(DayTable(self.data, verdict))
            if verdict.day is not None and verdict.day != problem.day:
                note = QLabel(f"This is {verdict.day:%A, %B} {verdict.day.day}.")
                note.setProperty("role", "soft")
                self.feedback_layout.addWidget(note)

    def _show_solved(self, text: str, earlier: bool) -> None:
        problem = self.problem
        self._feedback("good", "Solved ✓" if earlier else "Correct", problem.explain)
        others = [a for a in (problem.answer, *problem.alternatives) if _tidy(a) != _tidy(text)]
        if others:
            label = QLabel("Also correct:")
            label.setProperty("role", "soft")
            self.feedback_layout.addWidget(label)
            for other in others[:3]:
                self.feedback_layout.addWidget(_code(other))
        if not earlier:
            self.next_button.setFocus()

    def _hint(self) -> None:
        problem = self.problem
        if not problem.hints:
            return
        self.hints_shown = min(self.hints_shown + 1, len(problem.hints))
        self._feedback("hint", f"Hint {self.hints_shown} of {len(problem.hints)}", "")
        for hint in problem.hints[: self.hints_shown]:
            if "\n" in hint or hint.startswith(("REQUEST", "{", "PREFER", "IF", "EACH_OF")):
                self.feedback_layout.addWidget(_code(hint))
            else:
                label = QLabel(hint)
                label.setWordWrap(True)
                self.feedback_layout.addWidget(label)
        left = len(problem.hints) - self.hints_shown
        self.hint_button.setText(f"Hint ({left})" if left else "No more hints")
        self.hint_button.setEnabled(bool(left))

    def _reveal(self) -> None:
        problem = self.problem
        self._feedback("hint", "Answer", problem.explain)
        self.feedback_layout.addWidget(_code(problem.answer))
        use = QPushButton("Copy into the editor")
        use.setProperty("role", "link")
        use.clicked.connect(lambda: self.editor.setPlainText(problem.answer))
        self.feedback_layout.addWidget(use, alignment=Qt.AlignLeft)

    def _feedback(self, role: str, headline: str, detail: str) -> None:
        while self.feedback_layout.count():
            widget = self.feedback_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.feedback.setProperty("role", role)
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)
        title = QLabel(headline)
        font = title.font()
        font.setPointSizeF(font.pointSizeF() + 3)
        font.setBold(True)
        title.setFont(font)
        colour = {"good": style.LEAF, "bad": style.BERRY, "hint": style.INK}[role]
        title.setStyleSheet(f"color: {colour};")
        self.feedback_layout.addWidget(title)
        if detail:
            body = QLabel(detail)
            body.setWordWrap(True)
            self.feedback_layout.addWidget(body)
        self.feedback.setVisible(True)

    def _move_cursor(self, line: int, column: int) -> None:
        block = self.editor.document().findBlockByLineNumber(max(line - 1, 0))
        cursor = self.editor.textCursor()
        cursor.setPosition(block.position() + max(min(column - 1, block.length() - 1), 0))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    # -- the trail -------------------------------------------------------------------------

    def _refresh_trail(self) -> None:
        solved = 0
        for level_index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(level_index)
            level = self.levels[level_index]
            done = 0
            for problem in level.problems:
                attempt = self.progress.of(problem.id)
                item = self.items[problem.id]
                if attempt.solved:
                    mark, colour = SOLVED, style.LEAF
                    done += 1
                elif attempt.tries:
                    mark, colour = TRIED, style.SUN
                else:
                    mark, colour = NEW, style.SOFT
                item.setText(0, f"{mark}  {problem.title}")
                item.setForeground(0, QColor(colour if mark != NEW else style.INK))
            top.setText(0, f"{level_index + 1}. {level.name}   {done}/{len(level.problems)}")
            solved += done
        self.bar.setValue(solved)
        self.score.setText(f"{solved} of {len(self.problems)} problems solved")

    def _reset(self) -> None:
        sure = QMessageBox.question(
            self, "Start over?", "Forget every solved problem and everything written so far?"
        )
        if sure != QMessageBox.Yes:
            return
        self.progress.problems.clear()
        self.progress.save()
        self.problem = None
        self._refresh_trail()
        self.open_problem(self.problems[0])

    def _toggle_sheet(self) -> None:
        showing = not self.sheet.isVisible()
        self.sheet.setVisible(showing)
        self.sheet_button.setText("Hide the cheat sheet" if showing else "Show the cheat sheet")

    def welcome(self) -> None:
        """The first thing a new trainee sees: what the trainer is and how to use it."""
        WelcomeDialog(len(self.problems), len(self.levels), self).exec()
        self.progress.welcomed = True
        self.progress.save()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Keep what was written before going."""
        self._keep_draft()
        super().closeEvent(event)


class DayTable(QTableWidget):
    """A counterexample: a day the solver built, one row per person, one column per block."""

    def __init__(self, data: Dataset, verdict: Verdict) -> None:
        blocks = sorted(data.blocks_on(verdict.day or data.target), key=lambda b: b.start_minute)
        held = {}
        for a in verdict.schedule:
            held.setdefault((a.staff, a.block), []).append(a)
        people = [s for s in verdict.staff if any((s, b.id) in held for b in blocks)]
        people += [s for s in verdict.staff if s not in people][: max(0, 8 - len(people))]
        super().__init__(len(people), len(blocks))
        self.setHorizontalHeaderLabels([b.id.replace("_", " ") for b in blocks])
        self.setVerticalHeaderLabels([data.staff[s].name for s in people])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for row, person in enumerate(people):
            for column, block in enumerate(blocks):
                cell = QTableWidgetItem(_cell(data, held.get((person, block.id), []), block))
                if (person, block.id) in held:
                    filler = all(a.activity == FILLER for a in held[person, block.id])
                    cell.setBackground(QColor(style.PAPER if filler else style.SUN_BG))
                self.setItem(row, column, cell)
        self.verticalHeader().setDefaultSectionSize(28)
        header = self.horizontalHeader().sizeHint().height()
        bar = self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(min(header + 28 * len(people) + bar + 6, 380))


def _cell(data: Dataset, held: list, block) -> str:
    if not held:
        return "free"
    words = []
    for a in held:
        activity = data.activities.get(a.activity)
        name = activity.name if activity else a.activity
        if a.role:
            name += f" ({a.role})"
        if a.minutes < block.minutes:
            name += f", {a.minutes}m"
        words.append(name)
    return " + ".join(words)


class MappingView(QDialog):
    """One mapping's rows, to read: the trainer never writes to its copy of the sheets."""

    def __init__(self, data: Dataset, name: str, parent=None) -> None:
        super().__init__(parent)
        mapping = data.mappings[name]
        self.setWindowTitle(f"mappings.{name}")
        self.resize(560, 480)
        rows = sorted(mapping.rows.items())
        grid = QTableWidget(len(rows), len(mapping.keys) + 1)
        grid.setHorizontalHeaderLabels([*mapping.keys, "gives"])
        grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, (key, value) in enumerate(rows):
            for c, part in enumerate((*key, value)):
                grid.setItem(r, c, QTableWidgetItem(str(part)))
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"<b>mappings.{name}</b> takes {', '.join(mapping.keys)} and gives {mapping.value}."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(grid)
        if mapping.default:
            layout.addWidget(QLabel(f"With no row: <code>{mapping.default}</code>"))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class WelcomeDialog(QDialog):
    """A short note on what the trainer is and how it marks answers."""

    def __init__(self, problems: int, levels: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Skedge Training")
        self.resize(520, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        text = QLabel(
            f"<p>{problems} practice requests in {levels} levels, using the names and "
            "config from 2026 Main Season, Session 6. Nothing here touches a real schedule.</p>"
            "<p>Write each request in Skedge and press <b>Check my answer</b>. Answers are "
            "checked by what they do, not by how they're written: if yours differs, you'll "
            "see a day that shows the difference.</p>"
            "<p>Names and the calendar are on the right. Progress is saved.</p>"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        layout.addWidget(text, stretch=1)
        go = QPushButton("Start")
        go.setProperty("role", "primary")
        go.clicked.connect(self.accept)
        layout.addWidget(go, alignment=Qt.AlignRight)


def _code(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont("monospace"))
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"background: {style.SUNKEN}; border: 1px solid {style.LINE}; border-radius: 8px; "
        "padding: 8px;"
    )
    return label


def _tidy(text: str) -> str:
    return " ".join(text.split()).lower()
