"""The Configure pane: which Google account, and which sheets and folders to read.

Spreadsheet ids used to be typed into config.toml, one per sheet. Now there are two
directories to choose and everything inside them is found by name, so the pane is a row
each: what the directory is for, what is currently chosen, and a button that opens Drive to
change it. Changes are written when the pane is closed with Save, and the window then reads
everything again with what was chosen.

The account row is the same idea: it says who is signed in, and offers to sign in as
somebody else or to sign out. Signing out does not delete anything on Drive; it forgets
the token, and the next start asks again.
"""

from dataclasses import replace
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

from puppet_strings import google_auth
from puppet_strings.app.drive_browser import DriveBrowser
from puppet_strings.config import Config
from puppet_strings.drive import Drive
from puppet_strings.settings import FOLDERS, Chosen, load_settings, save_settings

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


class ConfigureDialog(QDialog):
    """Pick the Google account, the six spreadsheets, and the cabin act folder."""

    def __init__(self, config: Config, credentials: object | None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.credentials = credentials
        self.settings = load_settings()
        self.saved = False
        self.worker: _AccountWorker | None = None
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
