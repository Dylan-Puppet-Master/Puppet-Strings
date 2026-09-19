"""The groups pane: the shelves requests sit on, and what each one is for.

A request sits on one shelf. It joins the one being shown when it is made, and it is moved
by dragging its row onto another group's label — which is why there is no group to pick in
the editor: the pane is where a request's group is decided, all of it in one place.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings.app import palette
from puppet_strings.app.groups import ALL, DEFAULT_GROUPS, UNGROUPED
from puppet_strings.app.requests_model import REQUEST_IDS
from puppet_strings.app.store import RequestStore
from puppet_strings.sheets.requests import request_tabs


class GroupList(QListWidget):
    """The list of shelves, which a request can be dragged onto.

    Qt's own drop handling would move rows about inside the list, which is not what a drop
    here means, so the events are taken over: what lands is the ids of the requests being
    dragged, and where it lands is the group they join.
    """

    dropped = Signal(list, str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Take a drag of requests; ignore anything else dragged in from elsewhere."""
        self._consider(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        """Accept only over a group: `All requests` and `Ungrouped` are not shelves."""
        self._consider(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        """Move the dragged requests onto the group they were let go over."""
        group = self._group_at(event)
        if group is None:
            event.ignore()
            return
        ids = bytes(event.mimeData().data(REQUEST_IDS)).decode().split("\n")
        event.acceptProposedAction()
        self.dropped.emit([i for i in ids if i], group)

    def _consider(self, event) -> None:
        if self._group_at(event) is None:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def _group_at(self, event) -> str | None:
        """The group under the pointer, or None if a drop there would mean nothing."""
        if not event.mimeData().hasFormat(REQUEST_IDS):
            return None
        item = self.itemAt(event.position().toPoint())
        group = item.data(Qt.UserRole) if item else None
        return None if group in (None, ALL) else group


class GroupsPane(QWidget):
    """Every group, with how many requests are in it. Picking one filters the table.

    `All requests` and `Ungrouped` head the list and are not groups: nothing is ever in
    them but by not being somewhere else. They and the three default groups cannot be
    renamed or deleted.
    """

    chosen = Signal(str)
    dropped = Signal(list, str)  # request ids, and the group they were dragged onto
    retabbed = Signal(str)  # a group whose default tab was changed

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.list = GroupList()
        self.list.dropped.connect(self.dropped.emit)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._tab_menu)
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
        ungrouped = sum(1 for r in self.store.requests if not r.group)
        self._add(ALL, len(self.store.requests))
        self._add(UNGROUPED, ungrouped)
        for group in self.store.groups:
            self._add(group, self.store.count(group))
        self.list.setCurrentRow(self._row_of(wanted))
        self.list.blockSignals(False)
        self._enable()

    def _add(self, name: str, count: int) -> None:
        tab = self.store.group_tabs.of(name) if name not in (ALL, UNGROUPED) else ""
        item = QListWidgetItem(f"{name}  ({count})")
        item.setData(Qt.UserRole, name)
        if tab:
            item.setToolTip(f"New requests here are written to {tab}")
        if name in (ALL, UNGROUPED):
            item.setForeground(QColor(palette.QUIET))
        self.list.addItem(item)

    def _tab_menu(self, point) -> None:
        """Right-click a group to say which Requests tab its new requests go to."""
        item = self.list.itemAt(point)
        group = item.data(Qt.UserRole) if item else None
        if group is None or group in (ALL, UNGROUPED):
            return
        menu = QMenu(self)
        chosen = self.store.group_tabs.of(group)
        for tab in ("", *self._tabs()):
            action = menu.addAction(tab or "No tab of its own")
            action.setCheckable(True)
            action.setChecked(tab == chosen)
            action.triggered.connect(lambda _=False, t=tab: self._set_tab(group, t))
        menu.exec(self.list.viewport().mapToGlobal(point))

    def _tabs(self) -> tuple[str, ...]:
        """The tabs a request could be written to, for the span being scheduled."""
        dataset = self.store.dataset
        return request_tabs(dataset.this_span) if dataset is not None else ()

    def _set_tab(self, group: str, tab: str) -> None:
        """Remember where this group's new requests go, and say so on the label."""
        self.store.group_tabs.set(group, tab)
        self.refresh()
        self.retabbed.emit(group)

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
