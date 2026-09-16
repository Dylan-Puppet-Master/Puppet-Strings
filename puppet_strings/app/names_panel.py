"""A tree of every valid Skedge name, by namespace. Double-click inserts into the editor."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from puppet_strings.model import LIFEGUARD_ROLES, POSITION_ROLES, TRAINEE_ROLES, Dataset
from puppet_strings.skedge.resolve import TRAINEE, WEEKDAYS


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
        spaces = {
            "staff": [(i, s.name) for i, s in dataset.staff.items()]
            + [(c, f"category ({len(m)})") for c, m in dataset.staff_categories.items()],
            "activity": [(i, a.name) for i, a in dataset.activities.items()]
            + [(c, f"category ({len(m)})") for c, m in dataset.activity_categories.items()],
            "block": [(i, f"{b.start:%H:%M}-{b.end:%H:%M}") for i, b in dataset.blocks.items()]
            + [(c, f"category ({len(m)})") for c, m in dataset.block_categories.items()],
            "date": [("target", ""), ("session", "")] + [(d, "") for d in WEEKDAYS],
            "role": [(r, "position") for r in POSITION_ROLES[:3]]
            + [(r, "lifeguard") for r in LIFEGUARD_ROLES]
            + [(r, "trainee") for r in TRAINEE_ROLES + (TRAINEE,)],
            "metric": [(m, f"{v.scale_min}..{v.scale_max}") for m, v in dataset.metrics.items()],
        }
        for namespace, names in spaces.items():
            top = QTreeWidgetItem([namespace, ""])
            self.addTopLevelItem(top)
            for name, note in sorted(names):
                top.addChild(QTreeWidgetItem([f"{namespace}.{name}", note]))
        self.expandAll()
        self.resizeColumnToContents(0)
        self.collapseAll()

    def _pick(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is not None:
            self.picked.emit(item.text(0))
