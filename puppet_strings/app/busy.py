"""The panel shown while the solver works.

It is modal, so the window behind it takes no clicks while the schedule is being worked
out, and it carries the one thing still worth clicking: Cancel.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

STOPPING = "Stopping…"


class BusyDialog(QDialog):
    """A modal progress panel. Emits `cancelled` once, when the user asks to stop."""

    cancelled = Signal()

    def __init__(self, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Working")
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)  # Cancel is the way out
        self.setMinimumWidth(360)
        self.label = QLabel(message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # there is no percentage to report, so it just sweeps
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.ask_to_stop)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addLayout(buttons)

    def ask_to_stop(self) -> None:
        """Ask once, and say so: stopping is not instant."""
        if not self.cancel_button.isEnabled():
            return
        self.label.setText(STOPPING)
        self.cancel_button.setEnabled(False)
        self.cancelled.emit()

    def reject(self) -> None:
        """Escape asks the work to stop rather than leaving it running unattended."""
        self.ask_to_stop()

    def finish(self) -> None:
        """Take the panel down, the work it was waiting on having stopped.

        Closing goes through `reject`, which only asks, so ending it takes this instead.
        """
        self.done(QDialog.Accepted)
