"""A tree of every valid Skedge name, by namespace.

Names nest on their dots, so `activities.clinics.riflery` is three levels deep
rather than one line among hundreds. A node that is a name in its own right carries what it
stands for beside it, as a branch does for everything under it: `dates.session_4.week_2`
is every date of that week, as `staff` is everyone. A node that is only a step on the way
to a name, such as `dates` itself, does not.

Double-click opens a name to see what it stands for, which is the question the one-line
note cannot answer. Enter, or the right-click menu, puts it into the request being edited.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from puppet_strings.model import Dataset
from puppet_strings.skedge.namespaces import written
from puppet_strings.skedge.resolve import name_listing


class NamespacesPanel(QTreeWidget):
    """Namespaces as top-level items; names beneath, with the sheet value alongside."""

    picked = Signal(str)  # put this name into the request being edited
    inspected = Signal(str)  # show what this name stands for

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["name", "sheet value"])
        self.itemDoubleClicked.connect(self._inspect)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self, self._pick_current)
        # the names get longer the deeper they go, so the column follows what is open
        self.itemExpanded.connect(lambda _: self.resizeColumnToContents(0))
        self.itemCollapsed.connect(lambda _: self.resizeColumnToContents(0))

    def show_dataset(self, dataset: Dataset | None) -> None:
        """Fill the tree from a dataset."""
        self.clear()
        if dataset is None:
            return
        for namespace, names in name_listing(dataset).items():
            top = QTreeWidgetItem([namespace, ""])
            self.addTopLevelItem(top)
            nodes = {"": top}
            for name, note in names:
                node = self._branch(namespace, name, nodes)
                node.setText(1, note)
                node.setData(0, Qt.UserRole, written(namespace, name))  # a name, not just a step
        self.resizeColumnToContents(0)

    @staticmethod
    def _branch(namespace: str, name: str, nodes: dict[str, QTreeWidgetItem]) -> QTreeWidgetItem:
        """The node for a dotted name, making every node above it that is not there yet."""
        parts = name.split(".")
        for depth in range(1, len(parts) + 1):
            prefix = ".".join(parts[:depth])
            if prefix not in nodes:
                node = QTreeWidgetItem([f"{namespace}.{prefix}", ""])
                nodes[".".join(parts[: depth - 1])].addChild(node)
                nodes[prefix] = node
        return nodes[name]

    @property
    def current_name(self) -> str:
        """The name highlighted, or "" when the highlight is only a step on the way to one."""
        item = self.currentItem()
        return (item.data(0, Qt.UserRole) or "") if item is not None else ""

    def _inspect(self, item: QTreeWidgetItem, column: int) -> None:
        name = item.data(0, Qt.UserRole)
        if name:
            self.inspected.emit(name)

    def _pick_current(self) -> None:
        if self.current_name:
            self.picked.emit(self.current_name)

    def _menu(self, point) -> None:
        name = self.current_name
        if not name:
            return
        menu = QMenu(self)
        menu.addAction("Insert into the request", self._pick_current)
        menu.addAction("Show what it stands for", lambda: self.inspected.emit(name))
        menu.exec(self.viewport().mapToGlobal(point))
