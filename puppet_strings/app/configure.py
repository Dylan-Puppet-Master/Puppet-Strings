"""The Configure pane: which Google account, and which sheets and folders to read.

Spreadsheet ids used to be typed into config.toml, one per sheet. Now there are two
directories to choose and everything inside them is found by name, so the pane is a row
each: what the directory is for, what is currently chosen, and a button that opens Drive to
change it. Changes are written when the pane is closed with Save, and the window then reads
everything again with what was chosen.

The account row is the same idea: it says who is signed in, and offers to sign in as
somebody else or to sign out. Signing out does not delete anything on Drive; it forgets
the token, and the next start asks again.

The requests live on this computer rather than in a sheet, so this is also where they are
handed over: Export writes them to a file for the next Puppet Master, and Import takes one
in. Back up puts a copy on Drive, which the window also does once a run. And the Google
Sheets cache can be emptied here, for the rare edit Drive is slow to count.

The pane also opens the trainer, since it is the one window a new Puppet Master is sure to
see: on a first run it comes up before anything else, and the trainer needs no account.
"""

import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from puppet_strings import __version__, google_auth
from puppet_strings.app.drive_browser import DriveBrowser
from puppet_strings.backup import FOLDER, back_up_to
from puppet_strings.config import Config
from puppet_strings.drive import Drive
from puppet_strings.requests_db import SUFFIX, RequestDb
from puppet_strings.settings import FOLDERS, Chosen, load_settings, save_settings
from puppet_strings.sheets.cache import SheetCache
from puppet_strings.sheets.schedules import ROOT
from puppet_strings.sheets.source import LoadError
from puppet_strings.update import UpdateError, download, install, latest_release

NOT_CHOSEN = "not chosen"
SIGNED_OUT = "Not signed in"


class _AccountWorker(QThread):
    """Signing in opens a browser and waits for consent, which must not block the window."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:
        """Sign in and report the credentials, or why it did not happen."""
        try:
            self.done.emit(google_auth.sign_in(self.config))
        except google_auth.AuthError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(str(e))


class _Job(QThread):
    """One update job off the UI thread, so the pane keeps painting while it runs."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        """Do the job and report what it returned, or why it did not happen."""
        try:
            result = self.job()
        except UpdateError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(str(e))
        else:
            self.done.emit(result)


class ConfigureDialog(QDialog):
    """Pick the Google account, the six spreadsheets, and the cabin act folder."""

    def __init__(self, config: Config, credentials: object | None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.credentials = credentials
        self.settings = load_settings()
        self.saved = False
        self.worker: _AccountWorker | None = None
        self.updater: _Job | None = None
        self.installer: _Job | None = None
        self.backup: _Job | None = None
        self.rows: dict[tuple[str, str], QLabel] = {}  # (kind, name) -> the label showing it
        self.setWindowTitle("Configure Puppet Strings")
        self.resize(760, 560)

        self.account_label = QLabel(SIGNED_OUT)
        self.sign_in_button = QPushButton("Sign in")
        self.sign_in_button.clicked.connect(self.sign_in)
        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_button.clicked.connect(self.sign_out)
        client_button = QPushButton("OAuth client…")
        client_button.setToolTip(str(config.client_secrets))
        client_button.clicked.connect(self.choose_client)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._account_box(client_button))
        layout.addWidget(self._chosen_box("Directories", "folders", FOLDERS))
        layout.addWidget(self._requests_box())
        layout.addWidget(self._cache_box())
        layout.addWidget(self._updates_box())
        layout.addWidget(self._training_box())
        layout.addStretch(1)
        layout.addWidget(buttons)
        self.refresh_account()

    # -- building -----------------------------------------------------------------------

    def _account_box(self, client_button: QPushButton) -> QGroupBox:
        box = QGroupBox("Google account")
        row = QHBoxLayout(box)
        row.addWidget(self.account_label, stretch=1)
        for button in (client_button, self.sign_in_button, self.sign_out_button):
            row.addWidget(button)
        return box

    def _requests_box(self) -> QGroupBox:
        """How many requests this computer holds, and the buttons that hand them over."""
        box = QGroupBox("Requests")
        row = QHBoxLayout(box)
        self.book = RequestDb(self.config.requests)
        self.requests_label = QLabel()
        self.requests_label.setToolTip(str(self.book.path))
        self.requests_label.setWordWrap(True)
        self.backup_button = QPushButton("Back up")
        self.backup_button.setToolTip(f"Copy them to {FOLDER} in the Puppet Strings folder")
        self.backup_button.clicked.connect(self.back_up_requests)
        export = QPushButton("Export…")
        export.clicked.connect(self.export_requests)
        take = QPushButton("Import…")
        take.clicked.connect(self.import_requests)
        row.addWidget(self.requests_label, stretch=1)
        row.addWidget(self.backup_button)
        row.addWidget(export)
        row.addWidget(take)
        self._count_requests()
        return box

    def _cache_box(self) -> QGroupBox:
        box = QGroupBox("Google Sheets cache")
        row = QHBoxLayout(box)
        self.cache_label = QLabel("Sheets are kept on this computer until they change.")
        self.cache_label.setWordWrap(True)
        clear = QPushButton("Clear")
        clear.setEnabled(self.config.cache is not None)
        clear.clicked.connect(self.clear_cache)
        row.addWidget(self.cache_label, stretch=1)
        row.addWidget(clear)
        return box

    def _updates_box(self) -> QGroupBox:
        """Which version this is, and a button to go and look for a newer one."""
        box = QGroupBox("Version")
        row = QHBoxLayout(box)
        self.version_label = QLabel(f"Puppet Strings {__version__}")
        self.updates_button = QPushButton("Check for updates")
        self.updates_button.clicked.connect(self.check_for_updates)
        row.addWidget(self.version_label, stretch=1)
        row.addWidget(self.updates_button)
        return box

    def _training_box(self) -> QGroupBox:
        box = QGroupBox("Skedge training")
        row = QHBoxLayout(box)
        note = QLabel(
            "Practise writing requests on a sample session. No internet connection needed."
        )
        self.training_button = QPushButton("Open trainer")
        self.training_button.clicked.connect(self.open_trainer)
        row.addWidget(note, stretch=1)
        row.addWidget(self.training_button)
        return box

    # -- requests and the cache ---------------------------------------------------------

    def _count_requests(self, said: str = "") -> None:
        count = self.book.count()
        held = f"{count} request{'' if count == 1 else 's'} on this computer."
        self.requests_label.setText(f"{said} {held}".strip())

    def export_requests(self) -> None:
        """Write the requests to a file for another Puppet Master."""
        suggested = str(Path.home() / f"requests-{date.today().isoformat()}{SUFFIX}")
        picked, _ = QFileDialog.getSaveFileName(
            self, "Export requests", suggested, f"Requests (*{SUFFIX})"
        )
        if not picked:
            return
        target = Path(picked)
        if target.suffix != SUFFIX:
            target = target.with_name(target.name + SUFFIX)
        count = self.book.export(target)
        self._count_requests(f"Exported {count} to {target.name}.")

    def import_requests(self) -> None:
        """Replace the requests with a file another Puppet Master exported."""
        picked, _ = QFileDialog.getOpenFileName(
            self, "Import requests", str(Path.home()), f"Requests (*{SUFFIX})"
        )
        if not picked:
            return
        try:
            count, kept = self.book.import_file(Path(picked))
        except LoadError as e:
            QMessageBox.warning(self, "Import requests", str(e))
            return
        self.saved = True  # the window reads them in when this closes
        before = f" The ones they replaced are in {kept.name}." if kept else ""
        self._count_requests(f"Imported {count} from {Path(picked).name}.{before}")

    def back_up_requests(self) -> None:
        """Copy the requests to Drive, where a dead computer cannot take them.

        The folder chosen in this pane is the one used, saved or not: somebody who has just
        pointed Puppet Strings at another folder means that one.
        """
        if self.backup is not None:
            return
        chosen = self.settings.folders.get(ROOT)
        if self.credentials is None or chosen is None:
            QMessageBox.information(
                self,
                "Back up requests",
                "Sign in to Google and choose the Puppet Strings folder first.",
            )
            return
        self.backup_button.setEnabled(False)
        self._count_requests("Backing up…")
        self.backup = _Job(lambda: back_up_to(Drive(self.credentials), chosen.id, self.book))
        self.backup.done.connect(lambda name: self._count_requests(f"Backed up as {name}."))
        self.backup.failed.connect(self._backup_failed)
        self.backup.finished.connect(self._backup_finished)
        self.backup.start()

    def _backup_failed(self, why: str) -> None:
        self._count_requests()
        QMessageBox.warning(self, "Back up requests", why)

    def _backup_finished(self) -> None:
        self.backup = None
        self.backup_button.setEnabled(True)

    def clear_cache(self) -> None:
        """Empty the cache, so the next load reads every sheet from Google."""
        SheetCache(self.config.cache).clear()
        self.saved = True
        self.cache_label.setText("Cleared. Every sheet is read from Google on the next load.")

    # -- training -----------------------------------------------------------------------

    def open_trainer(self) -> None:
        """Start the trainer as a program of its own.

        It dresses the whole application in its own colours, so it cannot share a process
        with this window; and on a first run it keeps going if this pane is closed unsigned.
        """
        try:
            subprocess.Popen(trainer_command())
        except OSError as e:
            QMessageBox.warning(self, "Skedge training", f"Could not start the trainer: {e}")

    # -- updates ------------------------------------------------------------------------

    def check_for_updates(self) -> None:
        """Ask GitHub for a newer release, and offer to put it in place if there is one."""
        if self.updater is not None:
            return
        self.updates_button.setEnabled(False)
        self.version_label.setText("Looking for a newer version…")
        self.updater = _Job(lambda: latest_release(self.config.releases_url))
        self.updater.done.connect(self._update_found)
        self.updater.failed.connect(self._update_failed)
        self.updater.finished.connect(self._update_finished)
        self.updater.start()

    def _update_found(self, release) -> None:
        if release is None:
            self.version_label.setText(f"Puppet Strings {__version__} is the newest version.")
            return
        self.version_label.setText(f"Puppet Strings {__version__} — {release.version} is out")
        answer = QMessageBox.question(
            self,
            "Update available",
            f"Puppet Strings {release.version} is out. You have {__version__}.\n\n"
            f"{release.notes[:400]}\n\nDownload and install it now?",
        )
        if answer != QMessageBox.Yes:
            return
        self.updates_button.setEnabled(False)
        self.version_label.setText(f"Downloading {release.version}…")
        self.installer = _Job(lambda: install(download(release)))
        self.installer.done.connect(self._installed)
        self.installer.failed.connect(self._update_failed)
        self.installer.finished.connect(self._update_finished)
        self.installer.start()

    def _installed(self, where) -> None:
        self.version_label.setText(f"Installed. Restart Puppet Strings to use it. ({where})")

    def _update_failed(self, why: str) -> None:
        self.version_label.setText(f"Puppet Strings {__version__}")
        QMessageBox.warning(self, "Updates", why)

    def _update_finished(self) -> None:
        self.updater = self.installer = None
        self.updates_button.setEnabled(True)

    def _chosen_box(self, title: str, kind: str, entries: tuple) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for name, label, note in entries:
            shown = QLabel()
            shown.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.rows[kind, name] = shown
            browse = QPushButton("Browse Drive…")
            browse.clicked.connect(lambda _=False, k=kind, n=name: self.browse(k, n))
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _=False, k=kind, n=name: self.clear(k, n))
            line = QHBoxLayout()
            line.addWidget(shown, stretch=1)
            line.addWidget(browse)
            line.addWidget(clear)
            holder = QWidget()
            holder.setLayout(line)
            form.addRow(QLabel(f"{label}\n{note}"), holder)
            self._show(kind, name)
        return box

    # -- the account --------------------------------------------------------------------

    def refresh_account(self) -> None:
        """Say who is signed in, and offer only the buttons that would do something."""
        signed_in = self.credentials is not None and self.config.token.expanduser().exists()
        if signed_in:
            address = google_auth.account(self.credentials)
            self.account_label.setText(f"Signed in as {address}" if address else "Signed in")
        elif self.credentials is not None:
            self.account_label.setText("Using the service account in config.toml")
        else:
            self.account_label.setText(SIGNED_OUT)
        self.sign_in_button.setText("Switch account" if signed_in else "Sign in")
        self.sign_out_button.setEnabled(bool(signed_in))

    def sign_in(self) -> None:
        """Open a browser for consent; the window keeps painting while it waits."""
        if self.worker is not None:
            return
        self.account_label.setText("Waiting for the browser…")
        self.sign_in_button.setEnabled(False)
        self.worker = _AccountWorker(self.config)
        self.worker.done.connect(self._signed_in)
        self.worker.failed.connect(self._sign_in_failed)
        self.worker.finished.connect(self._sign_in_finished)
        self.worker.start()

    def _signed_in(self, credentials: object) -> None:
        self.credentials = credentials
        self.saved = True  # the account changed, so the window reloads even without Save
        self.refresh_account()

    def _sign_in_failed(self, message: str) -> None:
        self.refresh_account()
        QMessageBox.critical(self, "Could not sign in", message)

    def _sign_in_finished(self) -> None:
        self.worker = None
        self.sign_in_button.setEnabled(True)

    def sign_out(self) -> None:
        """Forget the account. Nothing on Drive changes."""
        google_auth.sign_out(self.config.token)
        self.credentials = None
        self.saved = True
        self.refresh_account()

    def choose_client(self) -> None:
        """Put the OAuth client JSON downloaded from Google where signing in looks for it."""
        picked, _ = QFileDialog.getOpenFileName(self, "OAuth client JSON", "", "JSON (*.json)")
        if not picked:
            return
        target = self.config.client_secrets.expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(picked).read_bytes())
        QMessageBox.information(self, "OAuth client", f"Saved to {target}. Now sign in.")

    # -- the sheets ---------------------------------------------------------------------

    def browse(self, kind: str, name: str) -> None:
        """Choose a spreadsheet or a folder from Drive."""
        if self.credentials is None:
            QMessageBox.information(self, "Sign in first", "Sign in to Google to browse Drive.")
            return
        browser = DriveBrowser(Drive(self.credentials), want_folder=kind == "folders", parent=self)
        if browser.exec() != QDialog.Accepted or browser.chosen is None:
            return
        self.choose(kind, name, Chosen(browser.chosen.id, browser.chosen.name))

    def choose(self, kind: str, name: str, chosen: Chosen) -> None:
        """Record a choice, without writing it until Save."""
        self.settings = replace(
            self.settings, **{kind: {**getattr(self.settings, kind), name: chosen}}
        )
        self._show(kind, name)

    def clear(self, kind: str, name: str) -> None:
        """Forget what was chosen for one sheet or folder."""
        picked = {i: c for i, c in getattr(self.settings, kind).items() if i != name}
        self.settings = replace(self.settings, **{kind: picked})
        self._show(kind, name)

    def _show(self, kind: str, name: str) -> None:
        chosen = getattr(self.settings, kind).get(name)
        label = self.rows[kind, name]
        if chosen is None:
            label.setText(NOT_CHOSEN)
            label.setToolTip("")
            return
        label.setText(chosen.name or chosen.id)
        label.setToolTip(chosen.id)

    def save(self) -> None:
        """Write the choices and close. The window reads everything again afterwards."""
        save_settings(self.settings)
        self.saved = True
        self.accept()


def trainer_command() -> list[str]:
    """How to start the trainer: this executable when packaged, else this Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "train"]
    return [sys.executable, "-m", "puppet_strings", "train"]
