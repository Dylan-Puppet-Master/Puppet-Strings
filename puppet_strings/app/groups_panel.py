"""The groups pane: switch between groups of requests, and make new ones."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app import palette
from puppet_strings.app.groups import ALL, DEFAULT_GROUPS, UNGROUPED
from puppet_strings.app.store import RequestStore


class GroupsPane(QWidget):
    """Every group, with how many requests are in it. Picking one filters the table.

    `All requests` and `Ungrouped` head the list and are not groups: nothing is ever in
    them but by not being somewhere else. They and the three default groups cannot be
    renamed or deleted.
    """

    chosen = Signal(str)

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._chosen)
        self.new_button = QPushButton("New")
        self.rename_button = QPushButton("Rename")
        self.delete_button = QPushButton("Delete")
        self.new_button.clicked.connect(self.new_group)
        self.rename_button.clicked.connect(self.rename_group)
        self.delete_button.clicked.connect(self.delete_group)
        buttons = QHBoxLayout()
        for button in (self.new_button, self.rename_button, self.delete_button):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        self.refresh()

    @property
    def current(self) -> str:
        """The group picked, `ALL`, or `UNGROUPED`."""
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else ALL

    def refresh(self, keep: str | None = None) -> None:
        """Rebuild the list from the store, staying on the group that was picked."""
        wanted = keep or self.current
        self.list.blockSignals(True)
        self.list.clear()
        ungrouped = sum(1 for r in self.store.requests if not r.groups)
        self._add(ALL, len(self.store.requests))
        self._add(UNGROUPED, ungrouped)
        for group in self.store.groups:
            self._add(group, self.store.count(group))
        self.list.setCurrentRow(self._row_of(wanted))
        self.list.blockSignals(False)
        self._enable()

    def _add(self, name: str, count: int) -> None:
        item = QListWidgetItem(f"{name}  ({count})")
        item.setData(Qt.UserRole, name)
        if name in (ALL, UNGROUPED):
            item.setForeground(QColor(palette.QUIET))
        self.list.addItem(item)

    def _row_of(self, name: str) -> int:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == name:
                return row
        return 0

    def _chosen(self, current, previous) -> None:
        self._enable()
        self.chosen.emit(self.current)

    def _enable(self) -> None:
        """A default group stays as it is; only the ones made here can be renamed or gone.

        Renaming a default group would leave the group itself behind, empty, because it is
        always in the list, so the button is off rather than misleading.
        """
        made_here = self.current not in (ALL, UNGROUPED, *DEFAULT_GROUPS)
        for button in (self.rename_button, self.delete_button):
            button.setEnabled(made_here)
            button.setToolTip("" if made_here else "Only groups you made can be renamed or deleted")

    def new_group(self) -> None:
        """Ask for a name and add the group, then switch to it."""
        name, ok = QInputDialog.getText(self, "New group", "Group name")
        if not ok:
            return
        added = self.store.add_group(name)
        if not added:
            QMessageBox.information(self, "New group", f"There is already a group called '{name}'.")
            return
        self.refresh(keep=added)
        self.chosen.emit(added)

    def rename_group(self) -> None:
        """Rename the group picked, everywhere it appears."""
        old = self.current
        name, ok = QInputDialog.getText(self, "Rename group", "Group name", text=old)
        if not ok:
            return
        renamed = self.store.rename_group(old, name)
        if not renamed:
            QMessageBox.information(self, "Rename group", f"'{name}' is not a free name.")
            return
        self.refresh(keep=renamed)
        self.chosen.emit(renamed)

    def delete_group(self) -> None:
        """Take the group off every request in it. The requests themselves stay."""
        group = self.current
        count = self.store.count(group)
        answer = QMessageBox.question(
            self,
            "Delete group",
            f"Delete the group '{group}'? Its {count} request(s) stay, ungrouped by it.",
        )
        if answer != QMessageBox.Yes:
            return
        self.store.delete_group(group)
        self.refresh(keep=ALL)
        self.chosen.emit(ALL)
