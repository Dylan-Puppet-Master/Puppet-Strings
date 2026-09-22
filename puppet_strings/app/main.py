"""The desktop request manager window."""

import sys
import traceback
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from puppet_strings import __version__
from puppet_strings.app import palette
from puppet_strings.app.busy import BusyDialog
from puppet_strings.app.calendar_pane import SessionCalendar
from puppet_strings.app.configure import ConfigureDialog
from puppet_strings.app.conflicts import summary
from puppet_strings.app.details import details, is_metric
from puppet_strings.app.details_dialog import DetailsDialog, MetricDialog
from puppet_strings.app.editor import RequestEditor
from puppet_strings.app.errors import summary as error_summary
from puppet_strings.app.errors_panel import ErrorsPane
from puppet_strings.app.facets import facets
from puppet_strings.app.groups import ALL, UNGROUPED
from puppet_strings.app.groups_panel import GroupsPane
from puppet_strings.app.namespaces_panel import NamespacesPanel
from puppet_strings.app.requests_model import RequestFilter, RequestsModel
from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog
from puppet_strings.app.schedule_dialog import ScheduleDialog
from puppet_strings.app.store import RequestStore
from puppet_strings.config import Config, load_config
from puppet_strings.google_auth import AuthError
from puppet_strings.model import WRITABLE_PRIORITIES
from puppet_strings.session import open_source
from puppet_strings.sheets.source import CsvSource, LoadError, NotACampDay
from puppet_strings.update import UpdateError, download, install, latest_release


def run_app(config: Config, fixtures: Path | None) -> int:
    """Open the window and run until it closes.

    A first run has nobody signed in to Google, so the Configure pane comes up before the
    window does: there is nothing to show until there is an account to read the sheets as.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    palette.apply(app)  # the window is a dark one whatever the desktop theme is
    if fixtures:
        store = RequestStore(CsvSource(fixtures), config)
    else:
        config, source = connect(config)
        if source is None:
            return 1
        store = RequestStore(source, config)
    window = MainWindow(store)
    window.show()
    window.reload()  # loads in the background; the window paints right away
    return app.exec()


def connect(config: Config, parent=None) -> tuple[Config, object | None]:
    """The sheets as whoever is signed in, asking them to sign in if nobody is.

    Returns the config as it stands afterwards and the source, or None for the source if
    the pane was closed without an account, which is the one case there is no going on from.
    """
    try:
        return config, open_source(config, None)
    except AuthError:
        pass
    dialog = ConfigureDialog(config, None, parent)
    dialog.exec()
    config = load_config()
    try:
        return config, open_source(config, None)
    except AuthError as e:
        QMessageBox.critical(parent, "Not signed in", str(e))
        return config, None


class LoadWorker(QThread):
    """Reads every sheet off the UI thread."""

    done = Signal()
    failed = Signal(str)
    not_a_camp_day = Signal(str)
    calendar = Signal(object)  # the Calendar sheet, read first and on its own

    def __init__(self, store: RequestStore, target: date) -> None:
        super().__init__()
        self.store = store
        self.target = target

    def run(self) -> None:
        """Load and report success or the error text.

        The Calendar goes out first, so the calendar pane fills in whether or not the rest
        of the sheets load: which week of which session a date is in is the Calendar sheet's
        to say, and a Skills tab with a bad row has no business emptying it.
        """
        # whatever is wrong with the Calendar, the load below is what says so
        with suppress(Exception):
            self.calendar.emit(self.store.calendar(self.target))
        try:
            self.store.load(self.target)
        except NotACampDay as e:
            self.not_a_camp_day.emit(str(e))
            return
        except LoadError as e:
            self.failed.emit(str(e))
            return
        except Exception:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(traceback.format_exc())
            return
        self.done.emit()


class Worker(QThread):
    """Runs one job off the UI thread, so the window keeps painting while it runs.

    A job that blocks the UI thread leaves the progress panel unpainted and its bar
    frozen, which looks like a hung window rather than a busy one.
    """

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


class SolveWorker(QThread):
    """Runs the solver off the UI thread. The solver is imported on first use, not at startup."""

    done = Signal(object)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, store: RequestStore, same_day: bool, cancel) -> None:
        super().__init__()
        self.store = store
        self.same_day = same_day
        self.cancel = cancel

    def run(self) -> None:
        """Solve and emit the result, the error text, or that it was stopped."""
        # already imported by run_solve
        from puppet_strings.solver.solve import Cancelled, RequestError, solve

        try:
            result = solve(self.store.current, self.store.config, self.same_day, self.cancel)
        except Cancelled:
            self.stopped.emit()
        except (RequestError, LoadError) as e:
            self.failed.emit(str(e))
        except Exception:  # noqa: BLE001 - shown to the user, never swallowed
            self.failed.emit(traceback.format_exc())
        else:
            self.done.emit(result)


class MainWindow(QMainWindow):
    """Request table with filters on the left, editor on the right, names panel docked."""

    def __init__(self, store: RequestStore) -> None:
        super().__init__()
        self.store = store
        self.worker: SolveWorker | None = None
        self.busy: BusyDialog | None = None
        self.progress: BusyDialog | None = None  # for work that cannot be cancelled
        self.loader: LoadWorker | None = None
        self.offerings: Worker | None = None
        self.updater: Worker | None = None
        self.installer: Worker | None = None
        self.checked_for_updates = False
        self.reload_requested = False
        self.setWindowTitle("Puppet Strings")
        self.resize(1300, 800)

        self.model = RequestsModel(store)
        self.proxy = RequestFilter(store)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setDragEnabled(True)  # a row is dragged onto a group to move it there
        self.table.setDragDropMode(QTableView.DragOnly)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._select)
        self.editor = RequestEditor()
        self.editor.saved.connect(self._saved)
        self.editor.deleted.connect(self._deleted)
        self.editor.new_requested.connect(self.new_request)
        self.names = NamespacesPanel()
        self.names.picked.connect(self.editor.insert_name)
        self.names.inspected.connect(self.inspect_name)
        self.calendar = SessionCalendar()
        self.calendar.picked.connect(self.insert_date)
        self.groups = GroupsPane(store)
        self.groups.chosen.connect(self._group_chosen)
        self.groups.dropped.connect(self._set_group)
        self.groups.retabbed.connect(lambda _: self.editor_new_if_empty())
        self.errors = ErrorsPane()
        self.errors.picked.connect(self.show_request)

        self._build_toolbar()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(self._build_filters())
        left_layout.addWidget(self.table)
        groups_box = QWidget()
        groups_layout = QVBoxLayout(groups_box)
        groups_layout.addWidget(QLabel("Groups"))
        groups_layout.addWidget(self.groups)
        splitter = QSplitter()
        splitter.addWidget(groups_box)
        splitter.addWidget(left)
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 3)
        self.setCentralWidget(splitter)
        names_dock = QDockWidget("Namespaces", self)
        names_dock.setWidget(self.names)
        self.addDockWidget(Qt.RightDockWidgetArea, names_dock)
        calendar_dock = QDockWidget("Calendar: click a date to insert it", self)
        calendar_dock.setWidget(self.calendar)
        self.addDockWidget(Qt.RightDockWidgetArea, calendar_dock)
        self.errors_dock = QDockWidget("Errors", self)
        self.errors_dock.setWidget(self.errors)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.errors_dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel("Target date "))
        self.date_edit = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        toolbar.addWidget(self.date_edit)
        toolbar.addAction("Reload", self.reload)
        toolbar.addAction("Load offerings", self.load_offerings)
        toolbar.addAction("Solve", self.run_solve)
        toolbar.addSeparator()
        self.same_day_action = toolbar.addAction("Same-day changes")
        self.same_day_action.setCheckable(True)
        self.same_day_action.setToolTip("Re-solve a published day, moving as few people as it can")
        self.same_day_action.toggled.connect(self._same_day_toggled)
        self.sleep_action = toolbar.addAction(SLEEP, lambda: self.open_same_day(SLEEP))
        self.sickness_action = toolbar.addAction(SICKNESS, lambda: self.open_same_day(SICKNESS))
        for action in (self.sleep_action, self.sickness_action):
            action.setVisible(False)  # only while changing a day that is already out
        self.status_label = QLabel("")
        # It can run to a paragraph of warnings, and a label that insists on its full width
        # pushes everything after it -- Configure included -- into the overflow menu.
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        toolbar.addWidget(self.status_label)
        spacer = QWidget()  # everything after this is pushed to the right-hand end
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction("Configure", self.configure)

    def check_for_updates(self, quietly: bool = False) -> None:
        """Ask GitHub whether a newer Puppet Strings has been published.

        Only ever quietly here: **Check for updates** lives in the Configure pane, beside
        the account and the folders, which is where everything else about this copy rather
        than about today's schedule is. What is left here is the look on the first load,
        which says nothing unless there is something to say — and nothing at all if the
        check fails, because nobody opening the window to schedule a day wants to be told
        about the state of the internet.
        """
        self.updater = Worker(lambda: latest_release(self.store.config.releases_url))
        self.updater.done.connect(lambda release: self._update_found(release, quietly))
        if not quietly:
            self.updater.failed.connect(lambda why: QMessageBox.warning(self, "Updates", why))
        self.updater.start()

    def _update_found(self, release, quietly: bool) -> None:
        """Offer the update, or say there is none if the Puppet Master asked."""
        if release is None:
            if not quietly:
                QMessageBox.information(
                    self, "Up to date", f"Puppet Strings {__version__} is the newest version."
                )
            return
        answer = QMessageBox.question(
            self,
            "Update available",
            f"Puppet Strings {release.version} is out. You have {__version__}.\n\n"
            f"{release.notes[:400]}\n\nDownload and install it now?",
        )
        if answer != QMessageBox.Yes:
            return
        self.installer = Worker(lambda: install(download(release)))
        self.installer.done.connect(
            lambda where: QMessageBox.information(
                self, "Update installed", f"Restart Puppet Strings to use it.\n\n{where}"
            )
        )
        self.installer.failed.connect(lambda why: QMessageBox.warning(self, "Updates", why))
        self.start_progress(f"Downloading {release.version}…")
        self.installer.finished.connect(self.end_progress)
        self.installer.start()

    def configure(self) -> None:
        """Choose the Google account and the sheets, then read everything again."""
        if self.store.fixtures:
            QMessageBox.information(
                self, "Configure", "This window is reading CSV fixtures, not Google Sheets."
            )
            return
        dialog = ConfigureDialog(self.store.config, self.store.credentials, self)
        dialog.exec()
        if not dialog.saved:
            return
        config, source = connect(load_config(), self)
        if source is None:
            return
        self.store.reconnect(source, config)
        self.reload()

    def _build_filters(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("search id, description, skedge")
        self.priority_filter = _combo(["any priority"] + [p.value for p in WRITABLE_PRIORITIES])
        self.tag_filter = _combo(["any tag"])
        self.staff_filter = _combo(["any staff"])
        self.activity_filter = _combo(["any activity"])
        self.date_check = QCheckBox("on date")
        self.date_filter = QDateEdit(self.date_edit.date())
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        self.date_filter.setCalendarPopup(True)
        # The filter follows the date being scheduled, which is what you are almost always
        # asking about; moving the filter to look at another day leaves the target alone.
        self.date_edit.dateChanged.connect(self.date_filter.setDate)
        combos = (
            self.priority_filter,
            self.tag_filter,
            self.staff_filter,
            self.activity_filter,
        )
        layout.addWidget(self.text_filter, stretch=2)  # the box worth having room
        for widget in (*combos, self.date_check, self.date_filter):
            layout.addWidget(widget)
        self.text_filter.textChanged.connect(self.apply_filters)
        for combo in combos:
            combo.currentIndexChanged.connect(self.apply_filters)
        self.date_check.toggled.connect(self.apply_filters)
        self.date_filter.dateChanged.connect(self.apply_filters)
        return layout

    def apply_filters(self) -> None:
        """Push the filter widgets' state into the proxy model."""
        self.proxy.set_filters(
            group=self.groups.current,
            text=self.text_filter.text(),
            priority=_choice(self.priority_filter),
            tag=_choice(self.tag_filter),
            staff=_choice(self.staff_filter),
            activity=_choice(self.activity_filter),
            date=self.date_filter.date().toPython() if self.date_check.isChecked() else None,
        )

    def show_request(self, request_id: str) -> None:
        """Open a request in the editor, and select its row when the table is showing it."""
        request = self.model.request(request_id)
        if request is None:
            return
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if self.proxy.data(index, Qt.UserRole).id == request_id:
                self.table.setCurrentIndex(index)
                return
        self.editor.show_request(request)  # filtered out of the table, but still editable

    def refresh_errors(self) -> tuple:
        """Show everything wrong with the requests, and return the conflicts and errors."""
        conflicts, errors = self.store.conflicts, self.store.errors
        self.errors.show_problems(conflicts, errors, self.store.requests)
        count = len(conflicts) + len(errors)
        self.errors_dock.setWindowTitle(f"Errors ({count})" if count else "Errors")
        return conflicts, errors

    def _group_chosen(self, group: str) -> None:
        """Show the group the pane switched to."""
        self.apply_filters()
        chosen = "" if group == ALL else f" in {group}"
        self.status_label.setText(f"  {self.proxy.rowCount()} requests{chosen}")

    def _requests(self, ids: list[str]) -> list:
        """The requests with these ids."""
        wanted = set(ids)
        return [r for r in self.store.requests if r.id in wanted]

    def _set_group(self, ids: list[str], group: str) -> None:
        """Move requests onto the group they were dragged to, and say so.

        `Ungrouped` is a shelf to drag onto like any other; what it means is off them all.
        """
        self.store.set_group(ids, "" if group == UNGROUPED else group)
        self._groups_changed()
        self.status_label.setText(f"  Moved {len(ids)} request(s) to {group}")

    def editor_new_if_empty(self) -> None:
        """Start a new request in the group being shown, if the editor is not on one.

        A group's tab is what its *new* requests get, so changing it refreshes the blank
        editor and leaves a request that is open alone.
        """
        if self.editor.original_id is None:
            self.new_request()

    def new_request(self) -> None:
        """Start a request on the shelf being shown, written where that shelf says."""
        group = self.groups.current
        group = "" if group in (ALL, UNGROUPED) else group
        self.editor.clear(group, self.store.group_tabs.of(group) if group else "")

    def _requests_changed(self) -> tuple:
        """The requests moved: the table, both panes and the filters all follow.

        Every way of changing them — saving, deleting, regrouping, loading the offerings —
        ends here, so none of them can forget a pane. Returns the conflicts and the errors
        found, which is what a caller that has just saved something wants to know about.
        """
        self.model.refresh()
        self.groups.refresh()
        self.editor.set_dataset(self.store.dataset, self.store.groups)
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        found = self.refresh_errors()
        self.apply_filters()
        return found

    def _groups_changed(self) -> None:
        """As above, and the editor shows the request again so its ticks catch up."""
        self._requests_changed()
        if self.editor.original_id:
            current = self.model.request(self.editor.original_id)
            if current is not None:
                self.editor.show_request(current)

    @property
    def target(self) -> date:
        """The date in the toolbar."""
        return self.date_edit.date().toPython()

    def reload(self) -> None:
        """Read every sheet again for the target date, in the background.

        A click while a load is running queues one more load for when it finishes.
        """
        if self.loader is not None:
            self.reload_requested = True
            return
        self.status_label.setText(f"  Loading {self.target}…")
        self.start_progress(f"Reading the sheets for {self.target}…")
        self.loader = LoadWorker(self.store, self.target)
        self.loader.done.connect(self._loaded)
        self.loader.calendar.connect(self._calendar_read)
        self.loader.failed.connect(self._load_failed)
        self.loader.not_a_camp_day.connect(self._not_a_camp_day)
        self.loader.finished.connect(self._load_finished)
        self.loader.start()

    def start_progress(self, message: str) -> None:
        """Put up a panel saying what the window is busy with, and paint it at once."""
        if self.progress is not None:
            return
        self.progress = BusyDialog(message, self, cancellable=False)
        self.progress.show()
        QApplication.processEvents()  # the panel is no use if it paints after the work

    def end_progress(self) -> None:
        """Take that panel down."""
        if self.progress is not None:
            self.progress.finish()
            self.progress = None

    def wait_for_load(self) -> None:
        """Block until background loads finish (used by tests)."""
        while self.loader is not None:
            self.loader.wait()
            QApplication.processEvents()

    def _load_finished(self) -> None:
        """The thread has stopped: drop it, and start the queued reload if any."""
        self.loader = None
        if self.reload_requested:
            self.reload_requested = False
            self.reload()

    def _calendar_read(self, calendar: dict) -> None:
        """Number and shade the calendar as soon as the Calendar sheet itself is read."""
        self.calendar.show_calendar(calendar, self.target)

    def _loaded(self) -> None:
        self.end_progress()
        if not self.checked_for_updates and getattr(sys, "frozen", False):
            # Once a run, once something has loaded, and only in a copy that was downloaded:
            # a checkout updates with git, so asking GitHub on its behalf is a request sent
            # every time anybody opens the window to no possible end.
            self.checked_for_updates = True
            self.check_for_updates(quietly=True)
        dataset = self.store.dataset
        if self.editor.original_id and self.model.request(self.editor.original_id) is None:
            self.new_request()  # the request shown was deleted on the sheet
        self.model.refresh()
        self.table.resizeColumnsToContents()
        self.editor.set_dataset(dataset, self.store.groups)
        self.groups.refresh()
        self.names.show_dataset(dataset)
        self._fill_combo(self.staff_filter, "any staff", sorted(dataset.staff))
        self._fill_combo(self.activity_filter, "any activity", sorted(dataset.activities))
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self.calendar.show_dataset(dataset)
        self._refresh_same_day()
        conflicts, errors = self.refresh_errors()
        today = [a.describe(dataset.staff[a.staff].name) for a in dataset.today_adjustments]
        state = "published" if dataset.baseline is not None else "not published"
        parts = [
            f"Loaded {len(self.store.requests)} requests",
            f"{dataset.target} is {state}",
            summary(conflicts),
            error_summary(errors),
        ]
        self._say(". ".join(parts + today + list(dataset.warnings)))

    def _say(self, message: str) -> None:
        """Put a message in the toolbar, with the whole of it on the tooltip."""
        self.status_label.setText(f"  {message}")
        self.status_label.setToolTip(message)

    def _load_failed(self, message: str) -> None:
        self.end_progress()
        self.status_label.setText("")
        QMessageBox.critical(self, "Could not load", message)

    def _not_a_camp_day(self, message: str) -> None:
        """A date camp is not running is a date to change, not a sheet to go and fix."""
        self.end_progress()
        self._say(message)
        QMessageBox.warning(self, "Not a camp day", message)

    @property
    def same_day(self) -> bool:
        """Whether the next solve should hold the published schedule together."""
        dataset = self.store.dataset
        checked = self.same_day_action.isChecked()
        return checked and dataset is not None and dataset.baseline is not None

    def _same_day_toggled(self, on: bool) -> None:
        """Turning it on moves to today, since that is the day people are changing."""
        dataset = self.store.dataset
        if on and dataset is not None and dataset.baseline is None:
            self.date_edit.setDate(QDate(date.today()))
            self.reload()
        self._refresh_same_day()

    def _refresh_same_day(self) -> None:
        """Same-day changes only make sense for a day that has been published."""
        dataset = self.store.dataset
        published = dataset is not None and dataset.baseline is not None
        self.same_day_action.setEnabled(published)
        if not published and self.same_day_action.isChecked():
            self.same_day_action.blockSignals(True)
            self.same_day_action.setChecked(False)
            self.same_day_action.blockSignals(False)
        for action in (self.sleep_action, self.sickness_action):
            action.setVisible(self.same_day)

    def open_same_day(self, kind: str) -> None:
        """Record a sleep agreement or a sickness for today."""
        if self.store.dataset is None:
            return
        dialog = SameDayDialog(self.store, kind, self)
        dialog.exec()
        if dialog.changed:
            self.reload()  # standing feeds eligibility, so read everything again

    def load_offerings(self) -> None:
        """Add the Offerings tab's clinics to the Requests sheet, in the background.

        The write goes out to the sheet, so it runs on a worker like the other slow jobs:
        on the UI thread the progress panel would sit there unpainted until it finished.
        """
        if self.store.dataset is None or self.offerings is not None:
            return
        self.start_progress(f"Loading the offerings for {self.target}…")
        self.offerings = Worker(self.store.load_offerings)
        self.offerings.done.connect(self._offerings_loaded)
        self.offerings.failed.connect(self._offerings_failed)
        self.offerings.finished.connect(self._offerings_finished)
        self.offerings.start()

    def wait_for_offerings(self) -> None:
        """Block until the offerings have been written (used by tests)."""
        while self.offerings is not None:
            self.offerings.wait()
            QApplication.processEvents()

    def _offerings_loaded(self, count: int) -> None:
        self.end_progress()
        self._requests_changed()
        self.status_label.setText(f"  Loaded {count} offerings for {self.target}")

    def _offerings_failed(self, message: str) -> None:
        self.end_progress()
        self.status_label.setText("")
        QMessageBox.critical(self, "Could not load the offerings", message)

    def _offerings_finished(self) -> None:
        self.offerings = None

    def inspect_name(self, name: str) -> None:
        """Open a name from the Namespaces pane: its metric table, or what it stands for."""
        if self.store.dataset is None:
            return
        if is_metric(name):
            MetricDialog(self.store.source, self.store.config, name.split(".")[-1], self).exec()
            return
        found = details(name, self.store.dataset)
        if found is not None:
            DetailsDialog(found, self).exec()

    def insert_date(self, day: date) -> None:
        """Put a clicked calendar date into the Skedge editor at the cursor."""
        self.editor.insert_name(day.isoformat())

    def run_solve(self) -> None:
        """Solve the target date in the background, then show the schedule dialog."""
        if self.store.dataset is None or self.worker is not None:
            return
        if not self.store.offerings_loaded:
            answer = QMessageBox.question(
                self, "No offerings loaded", f"No offerings loaded for {self.target}. Solve anyway?"
            )
            if answer != QMessageBox.Yes:
                return
        # import on the main thread; a QThread import crashes
        from puppet_strings.solver.solve import Cancel

        self.status_label.setText("  Solving…")
        self.busy = BusyDialog(f"Solving {self.target}…", self)
        cancel = Cancel()
        self.busy.cancelled.connect(cancel.stop)
        self.worker = SolveWorker(self.store, self.same_day, cancel)
        self.worker.done.connect(self._solved)
        self.worker.failed.connect(self._solve_failed)
        self.worker.stopped.connect(self._solve_stopped)
        self.worker.finished.connect(self._solve_finished)
        self.worker.start()
        self.busy.show()  # shown, not run: the solve reports back through the event loop

    def _close_busy(self) -> None:
        """Take the panel down before anything else claims the screen."""
        if self.busy is not None:
            self.busy.finish()
            self.busy = None

    def _solve_finished(self) -> None:
        self.worker = None
        self._close_busy()

    def _solved(self, result) -> None:
        self._close_busy()
        self.status_label.setText("")
        ScheduleDialog(
            self.store.source, self.store.config, self.store.current, result, self
        ).exec()

    def _solve_stopped(self) -> None:
        self._close_busy()
        self.status_label.setText("  Solve cancelled")

    def _solve_failed(self, message: str) -> None:
        self._close_busy()
        self.status_label.setText("")
        QMessageBox.critical(self, "Solve failed", message)

    def _select(self, current, previous) -> None:
        """Open whatever row is now current; a row on its way out maps to nothing."""
        request = self.proxy.data(current, Qt.UserRole) if current.isValid() else None
        if request is not None:
            self.editor.show_request(request)

    def _saved(self, request, original_id) -> None:
        """Write one request to the sheet, and leave the editor saying that it is written."""
        if not self._covers_or_agreed(request):
            self.editor.not_saved("Not saved; still editing")
            self.status_label.setText("  Not saved; still editing")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)  # the sheet write is what takes the time
        try:
            saved = self.store.save(request, original_id)
        finally:
            QApplication.restoreOverrideCursor()
        conflicts, errors = self._requests_changed()
        clashes = [c for c in conflicts if saved.id in c.requests]
        wrong = [e for e in errors if e.request == saved.id]
        note = f"; it conflicts with {len(clashes)} other request(s)" if clashes else ""
        note += f"; {len(wrong)} error(s) in it" if wrong else ""
        self.editor.saved_as(saved, note)  # last, so nothing else overwrites the confirmation
        self.status_label.setText(f"  Saved {saved.id}{note}")

    def _covers_or_agreed(self, request) -> bool:
        """Warn before saving a request that says nothing about the date being scheduled.

        Such a request is perfectly good — it is about other dates — but it will vanish
        from the table the moment it is saved, so it is worth saying so first.
        """
        dataset = self.store.dataset
        if dataset is None:
            return True
        facet = facets(request, dataset)
        if not facet.valid or facet.covers(dataset.target):
            return True
        listed = ", ".join(d.isoformat() for d in sorted(facet.dates)[:3])
        when = listed or "no date on the calendar"
        if len(facet.dates) > 3:
            when += f" and {len(facet.dates) - 3} more"
        answer = QMessageBox.question(
            self,
            "Not about this date",
            f"This request does not cover {dataset.target}, the date being scheduled.\n"
            f"It is about: {when}.\n\n"
            "Save it anyway? It will apply on those dates and do nothing on this one.",
            QMessageBox.Save | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Save

    def _deleted(self, request_id: str) -> None:
        self.store.delete(request_id)
        self._requests_changed()
        self.status_label.setText(f"  Deleted {request_id}")

    @staticmethod
    def _fill_combo(combo: QComboBox, first: str, items: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([first, *items])
        combo.setCurrentText(current if current in items else first)
        combo.blockSignals(False)


def _combo(items: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    return combo


def _choice(combo: QComboBox) -> str | None:
    return None if combo.currentIndex() == 0 else combo.currentText()
