"""A tree of every valid Skedge name, by namespace. Double-click inserts into the editor."""

from PySide6.QtCore import Signal
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

    def show_dataset(self, dataset: Dataset | None) -> None:
        """Fill the tree from a dataset."""
        self.clear()
        if dataset is None:
            return
        for namespace, names in name_listing(dataset).items():
            top = QTreeWidgetItem([namespace, ""])
            self.addTopLevelItem(top)
            for name, note in names:
                top.addChild(QTreeWidgetItem([f"{namespace}.{name}", note]))
        self.expandAll()
        self.resizeColumnToContents(0)
        self.collapseAll()

    def _pick(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is not None:
            self.picked.emit(item.text(0))
