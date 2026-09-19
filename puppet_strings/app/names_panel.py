"""A tree of every valid Skedge name, by namespace. Double-click inserts into the editor.

Names nest on their dots, so `dates.session.four.second_week.monday` is five levels deep
rather than one line among hundreds. A node that is a name in its own right — `dates.session.four`
is a name as well as a parent — carries what it stands for beside it and can be inserted;
a node that is only a step on the way to one, such as `dates.session`, cannot.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from puppet_strings.model import Dataset
from puppet_strings.skedge.resolve import name_listing


class NamesPanel(QTreeWidget):
    """Namespaces as top-level items; names beneath, with the sheet value alongside."""

    picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["name", "sheet value"])
        self.itemDoubleClicked.connect(self._pick)
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
                node.setData(0, Qt.UserRole, f"{namespace}.{name}")  # a name, not just a step
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

    def _pick(self, item: QTreeWidgetItem, column: int) -> None:
        name = item.data(0, Qt.UserRole)
        if name:
            self.picked.emit(name)
