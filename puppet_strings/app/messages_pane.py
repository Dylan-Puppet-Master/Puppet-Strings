"""The messages pane: everything the window has to say, kept.

Each message is kept with the time it was said, and each part of it — requests loaded,
whether the day is published, the conflicts, each warning — on a line of its own.
"""

from datetime import datetime

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from puppet_strings.app import palette

MOST = 2000  # lines kept; the oldest go first
TIME = QColor(palette.QUIET)


class MessagesPane(QTreeWidget):
    """The time of each message, and its parts beneath it, newest at the bottom."""

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["time", "message"])
        self.setHeaderHidden(True)  # a time and what was said need no labels
        self.setColumnWidth(0, 80)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(True)

    def add(self, parts: list[str]) -> None:
        """Keep a message: its first part beside the time, the rest under it."""
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            return
        stamp = f"{datetime.now():%H:%M:%S}"
        for i, part in enumerate(parts):
            item = QTreeWidgetItem([stamp if i == 0 else "", part])
            item.setForeground(0, QBrush(TIME))
            item.setToolTip(1, part)
            self.addTopLevelItem(item)
        while self.topLevelItemCount() > MOST:
            self.takeTopLevelItem(0)
        self.scrollToBottom()

    def lines(self) -> list[str]:
        """What the pane says, a line per row (used by tests)."""
        return [self.topLevelItem(i).text(1) for i in range(self.topLevelItemCount())]
