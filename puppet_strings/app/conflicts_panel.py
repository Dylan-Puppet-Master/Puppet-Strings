"""The conflicts pane: requests that contradict each other, grouped by where they collide."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from puppet_strings.app.conflicts import Conflict
from puppet_strings.model import Request

CLASH = QColor("#b00020")
SLOT = QColor("#fdeef0")  # the heading's own background, so a group reads as one thing
REASON = QColor("#6b6b6b")


class ConflictsPane(QTreeWidget):
    """One group per collision: where it is, why, and every request caught in it.

    A conflict is a slot — one person, one date, one block — that two requests cannot both
    have. Everything under a heading belongs to that one collision, so a request that is in
    two of them appears under both.
    """

    picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["request", "priority", "what it says"])
        self.setColumnWidth(0, 260)
        self.setRootIsDecorated(True)
        self.itemDoubleClicked.connect(self._pick)

    def show_conflicts(self, conflicts: tuple[Conflict, ...], requests: list[Request]) -> None:
        """Fill the tree. Each heading is a slot; its children are the requests and reasons."""
        self.clear()
        by_id = {r.id: r for r in requests}
        for conflict in conflicts:
            self.addTopLevelItem(_group(conflict, by_id))
        self.expandAll()

    def _pick(self, item: QTreeWidgetItem, column: int) -> None:
        request_id = item.data(0, Qt.UserRole)
        if request_id:
            self.picked.emit(request_id)


def _group(conflict: Conflict, by_id: dict[str, Request]) -> QTreeWidgetItem:
    """One collision: a heading saying where, then what each request wants, then why."""
    heading = QTreeWidgetItem([conflict.where, "", _headline(conflict)])
    font = QFont(heading.font(0))
    font.setBold(True)
    for column in range(3):
        heading.setFont(column, font if column == 0 else heading.font(column))
        heading.setBackground(column, QBrush(SLOT))
    heading.setForeground(0, QBrush(CLASH))
    for request_id in conflict.requests:
        request = by_id.get(request_id)
        priority = request.priority.value if request else ""
        child = QTreeWidgetItem([request_id, priority, request.description if request else ""])
        child.setData(0, Qt.UserRole, request_id)
        child.setToolTip(2, request.skedge if request else "")
        heading.addChild(child)
    for reason in conflict.reasons[1:] if len(conflict.reasons) > 1 else ():
        note = QTreeWidgetItem(["", "", reason])  # the first is already in the heading
        note.setForeground(2, QBrush(REASON))
        heading.addChild(note)
    return heading


def _headline(conflict: Conflict) -> str:
    """The first reason, and how many more there are."""
    first = conflict.reasons[0]
    rest = len(conflict.reasons) - 1
    return f"{first} (and {rest} more)" if rest else first
