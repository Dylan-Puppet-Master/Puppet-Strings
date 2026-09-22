"""One job on a thread of its own, so the window keeps painting while it runs.

A job that blocks the UI thread leaves the panel saying what is happening unpainted and its
bar frozen, which looks like a hung window rather than a busy one. Every job that talks to
Google goes through here.
"""

import traceback

from PySide6.QtCore import QThread, Signal

from puppet_strings.sheets.source import LoadError
from puppet_strings.update import UpdateError


class Worker(QThread):
    """Runs one job off the UI thread and says what it returned, or what went wrong."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        """Do the job and report what it returned, or the error text."""
        try:
            result = self.job()
        except (LoadError, UpdateError) as e:
            self.failed.emit(str(e))  # these say what went wrong; a traceback would not
        except Exception:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(traceback.format_exc())
        else:
            self.done.emit(result)
