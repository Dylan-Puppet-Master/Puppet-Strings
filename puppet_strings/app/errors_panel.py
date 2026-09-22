"""The errors pane: everything wrong with the requests that can be seen without solving.

Two kinds of thing sit in it. A **conflict** is two requests that cannot both be kept
(`app.conflicts`); an **error** is one request asking for something the sheets rule out
(`app.errors`) — somebody who is not checked off, a clinic the day does not run. Both are
about a slot and both name the requests to go and look at, so both are shown the same way
and in one place: what the pane is for is the list of things to see to before solving.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from puppet_strings.app import palette
from puppet_strings.app.conflicts import Conflict
from puppet_strings.app.errors import Problem
from puppet_strings.model import Request

CLASH = QColor(palette.BAD)
SLOT = QColor(palette.CLASH)  # the heading's own background, so a group reads as one thing
INK = QColor(palette.INK)  # what to write on that background, rather than asking the palette
REASON = QColor(palette.QUIET)


class ErrorsPane(QTreeWidget):
    """One group per thing to see to: where it is, what is wrong, and which requests.

    A conflict is a slot — one person, one date, one block — that two requests cannot both
    have. Everything under a heading belongs to that one collision, so a request that is in
    two of them appears under both. An error is one request and one reason, and is shown
    the same way so that the pane reads as one list rather than two.

    Conflicts come first: a conflict is a day that cannot be built at all, and an error is
    a request that will not be met.
    """

    picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["request", "priority", "what it says"])
        self.setColumnWidth(0, 260)
        self.setRootIsDecorated(True)
        self.itemDoubleClicked.connect(self._pick)

    def show_problems(
        self,
        conflicts: tuple[Conflict, ...],
        errors: tuple[Problem, ...],
        requests: list[Request],
    ) -> None:
        """Fill the tree. Each heading is a slot; its children are the requests and reasons."""
        self.clear()
        by_id = {r.id: r for r in requests}
        for conflict in conflicts:
            self.addTopLevelItem(_group(conflict, by_id))
        for problem in errors:
            self.addTopLevelItem(_error(problem, by_id))
        self.expandAll()

    def _pick(self, item: QTreeWidgetItem, column: int) -> None:
        request_id = item.data(0, Qt.UserRole)
        if request_id:
            self.picked.emit(request_id)


def _group(conflict: Conflict, by_id: dict[str, Request]) -> QTreeWidgetItem:
    """One collision: a heading saying where, then what each request wants, then why."""
    heading = _heading(conflict.where, _headline(conflict))
    for request_id in conflict.requests:
        heading.addChild(_request_row(request_id, by_id))
    for reason in conflict.reasons[1:] if len(conflict.reasons) > 1 else ():
        note = QTreeWidgetItem(["", "", reason])  # the first is already in the heading
        note.setForeground(2, QBrush(REASON))
        heading.addChild(note)
    return heading


def _error(problem: Problem, by_id: dict[str, Request]) -> QTreeWidgetItem:
    """One error: where it is and what is wrong, then the request that asks for it."""
    heading = _heading(problem.where, problem.message)
    heading.addChild(_request_row(problem.request, by_id))
    return heading


def _request_row(request_id: str, by_id: dict[str, Request]) -> QTreeWidgetItem:
    """The row for one request under a heading: its id, priority and description."""
    request = by_id.get(request_id)
    priority = request.priority.value if request else ""
    row = QTreeWidgetItem([request_id, priority, request.description if request else ""])
    row.setData(0, Qt.UserRole, request_id)
    row.setToolTip(2, request.skedge if request else "")
    return row


def _heading(where: str, says: str) -> QTreeWidgetItem:
    """A group's own row: the slot, and the first thing wrong with it."""
    heading = QTreeWidgetItem([where, "", says])
    font = QFont(heading.font(0))
    font.setBold(True)
    for column in range(3):
        heading.setFont(column, font if column == 0 else heading.font(column))
        heading.setBackground(column, QBrush(SLOT))
        # the heading carries a colour of its own, so every column says what to write on
        # it rather than leaving the last two to the palette's ordinary text colour
        heading.setForeground(column, QBrush(CLASH if column == 0 else INK))
    return heading


def _headline(conflict: Conflict) -> str:
    """The first reason, and how many more there are."""
    first = conflict.reasons[0]
    rest = len(conflict.reasons) - 1
    return f"{first} (and {rest} more)" if rest else first
