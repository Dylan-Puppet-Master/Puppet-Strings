"""Browsing Google Drive from inside Puppet Strings, to choose a spreadsheet or a folder.

The alternative was asking for a Drive id, which means opening a browser, finding the
sheet, and copying the middle of its address. This shows the same three places Drive's own
sidebar does — My Drive, Shared with me, Shared drives — and a trail of folders above the
listing, so a sheet is chosen where it lives.

Listing a folder is a network call, so it happens on a worker and the dialog says it is
loading rather than freezing. Only folders and spreadsheets are ever listed: nothing else
can be picked, so nothing else is worth showing.
"""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from puppet_strings.drive import MY_DRIVE, SHARED_DRIVES, SHARED_WITH_ME, DriveError, DriveFile

# The places Drive itself offers, and what each is called here.
ROOTS = (
    (MY_DRIVE, "My Drive"),
    (SHARED_WITH_ME, "Shared with me"),
    (SHARED_DRIVES, "Shared drives"),
)


class _ListWorker(QThread):
    """One folder's contents, fetched off the UI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, drive, place: str) -> None:
        super().__init__()
        self.drive, self.place = drive, place

    def run(self) -> None:
        """List the place and report what is in it, or why it could not be listed."""
        try:
            self.done.emit(self.drive.listing(self.place))
        except DriveError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(str(e))


class DriveBrowser(QDialog):
    """Pick one spreadsheet, or one folder, from Drive.

    `want_folder` says which: choosing a folder means the Select button acts on wherever
    the listing currently is, because a folder is a place rather than a row.
    """

    def __init__(self, drive, want_folder: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.drive = drive
        self.want_folder = want_folder
        self.chosen: DriveFile | None = None
        self.trail: list[DriveFile] = []  # where the listing is, root first
        self.worker: _ListWorker | None = None
        self.setWindowTitle("Choose a folder" if want_folder else "Choose a spreadsheet")
        self.resize(640, 480)

        self.places = QListWidget()
        self.places.setMaximumWidth(170)
        for place, label in ROOTS:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, DriveFile(place, label, "application/vnd.google-apps.folder"))
            self.places.addItem(item)
        self.places.currentRowChanged.connect(self._place_picked)

        self.crumbs = QLabel("")
        self.crumbs.setWordWrap(True)
        self.up_button = QPushButton("Up")
        self.up_button.clicked.connect(self.go_up)
        self.listing = QListWidget()
        self.listing.setSelectionMode(QAbstractItemView.SingleSelection)
        self.listing.itemDoubleClicked.connect(self._opened)
        self.listing.currentItemChanged.connect(lambda *_: self._refresh_buttons())

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.select_button = buttons.addButton("Select", QDialogButtonBox.AcceptRole)
        self.select_button.clicked.connect(self._selected)
        buttons.rejected.connect(self.reject)

        above = QHBoxLayout()
        above.addWidget(self.up_button)
        above.addWidget(self.crumbs, stretch=1)
        right = QVBoxLayout()
        right.addLayout(above)
        right.addWidget(self.listing)
        body = QHBoxLayout()
        body.addWidget(self.places)
        body.addLayout(right, stretch=1)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Double-click a folder to open it."
                + ("" if want_folder else " Pick a spreadsheet, then Select.")
            )
        )
        layout.addLayout(body)
        layout.addWidget(buttons)
        self.places.setCurrentRow(0)

    # -- moving around ------------------------------------------------------------------

    def _place_picked(self, row: int) -> None:
        if row < 0:
            return
        self.trail = [self.places.item(row).data(Qt.UserRole)]
        self._load()

    def open_folder(self, folder: DriveFile) -> None:
        """Go into a folder, adding it to the trail."""
        self.trail.append(folder)
        self._load()

    def go_up(self) -> None:
        """Back to the folder above, or nowhere if already at a root."""
        if len(self.trail) > 1:
            self.trail.pop()
            self._load()

    def _opened(self, item: QListWidgetItem) -> None:
        found = item.data(Qt.UserRole)
        if found is not None and found.folder:
            self.open_folder(found)

    def _load(self) -> None:
        """List wherever the trail now ends, on a worker."""
        self.crumbs.setText(" / ".join(f.name for f in self.trail))
        self.listing.clear()
        self.listing.addItem("Loading…")
        self.listing.setEnabled(False)
        self._refresh_buttons()
        if self.worker is not None:
            self.worker.wait()
        self.worker = _ListWorker(self.drive, self.trail[-1].id)
        self.worker.done.connect(self._listed)
        self.worker.failed.connect(self._list_failed)
        self.worker.start()

    def wait_for_listing(self) -> None:
        """Block until the listing has arrived (used by tests)."""
        from PySide6.QtWidgets import QApplication

        while self.worker is not None and self.worker.isRunning():
            self.worker.wait()
            QApplication.processEvents()

    def _listed(self, found: list[DriveFile]) -> None:
        self.listing.clear()
        self.listing.setEnabled(True)
        for drive_file in found:
            item = QListWidgetItem(("📁  " if drive_file.folder else "📄  ") + drive_file.name)
            item.setData(Qt.UserRole, drive_file)
            self.listing.addItem(item)
        if not found:
            self.listing.addItem("Nothing here")
        self._refresh_buttons()

    def _list_failed(self, message: str) -> None:
        self.listing.clear()
        self.listing.setEnabled(True)
        self.listing.addItem(f"Could not list this folder: {message}")
        self._refresh_buttons()

    # -- choosing -----------------------------------------------------------------------

    @property
    def highlighted(self) -> DriveFile | None:
        """The row picked out in the listing, if it is a real one."""
        item = self.listing.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    @property
    def selection(self) -> DriveFile | None:
        """What Select would choose: the folder being shown, or the sheet picked in it."""
        if self.want_folder:
            found = self.highlighted
            if found is not None and found.folder:
                return found
            return self.trail[-1] if len(self.trail) > 1 else None
        found = self.highlighted
        return found if found is not None and not found.folder else None

    def _refresh_buttons(self) -> None:
        self.up_button.setEnabled(len(self.trail) > 1)
        self.select_button.setEnabled(self.selection is not None)

    def _selected(self) -> None:
        self.chosen = self.selection
        if self.chosen is not None:
            self.accept()
