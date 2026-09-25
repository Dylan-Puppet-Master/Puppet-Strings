"""The desktop request manager window."""

import sys
import traceback
from contextlib import suppress
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QAbstractSpinBox,
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
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from puppet_strings import __version__
from puppet_strings.app import palette
from puppet_strings.app.busy import BusyDialog
from puppet_strings.app.calendar_pane import SessionCalendar
from puppet_strings.app.canvas.view import Canvas
from puppet_strings.app.configure import ConfigureDialog
from puppet_strings.app.conflicts import summary
from puppet_strings.app.details import details, is_mapping
from puppet_strings.app.details_dialog import DetailsDialog, MappingDialog
from puppet_strings.app.editor import RequestEditor
from puppet_strings.app.errors import summary as error_summary
from puppet_strings.app.errors_panel import ErrorsPane
from puppet_strings.app.facets import facets
from puppet_strings.app.groups import ALL, UNGROUPED
from puppet_strings.app.groups_panel import GroupsPane
from puppet_strings.app.namespaces_panel import NamespacesPanel
from puppet_strings.app.request_table import RequestTable
from puppet_strings.app.requests_model import RequestFilter, RequestsModel
from puppet_strings.app.same_day import SICKNESS, SLEEP, SameDayDialog
from puppet_strings.app.schedule_dialog import ScheduleDialog
from puppet_strings.app.store import RequestStore
from puppet_strings.app.worker import Worker
from puppet_strings.config import Config, load_config
from puppet_strings.exclude import mentions_exclusion
from puppet_strings.google_auth import AuthError
from puppet_strings.model import WRITABLE_PRIORITIES, Dataset
from puppet_strings.session import open_source
from puppet_strings.settings import CANVAS, TABLE, load_settings, save_settings
from puppet_strings.sheets.source import CsvSource, LoadError, NotACampDay
from puppet_strings.update import download, install, latest_release


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
    window.show()  # only the calendar is read until Reload: the day wanted is often not the default
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
        self.dataset: Dataset | None = None  # what was solved, for the dialog to publish

    def run(self) -> None:
        """Solve and emit the result, the error text, or that it was stopped.

        The published days behind the target are read here rather than at load time: they
        are a spreadsheet each and only the solver reads them, so the wait belongs to the
        solve, where there is already a panel up saying what is happening.
        """
        # already imported by run_solve
        from puppet_strings.solver.solve import Cancelled, RequestError, solve

        try:
            self.dataset = self.store.for_solving()
            known = self.store.resolutions()
            result = solve(self.dataset, self.store.config, self.same_day, self.cancel, known)
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
        self.history: Worker | None = None  # the past days, read while the day is read over
        self.calendar_reader: Worker | None = None  # the Calendar sheet, read on opening
        self.history_wanted = False
        self.updater: Worker | None = None
        self.installer: Worker | None = None
        self.backup: Worker | None = None  # the requests, copied to Drive when they change
        self.adjuster: Worker | None = None  # the Adjustments tab, written after the dialog
        self.adjustments_waiting = False  # recorded while a write was running; write again
        self.checked_for_updates = False
        self.reload_requested = False
        # The date whose load last failed: said once, and read again only on Reload.
        self.failed_target: date | None = None
        self.setWindowTitle("Puppet Strings")
        self.resize(1300, 800)

        self.model = RequestsModel(store)
        self.proxy = RequestFilter(store)
        self.proxy.setSourceModel(self.model)
        self.table = RequestTable()  # a row is dragged onto a group to move it there
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._select)
        self.table.delete_requested.connect(self.delete_selected)
        self.editor = RequestEditor()
        self.editor.saved.connect(self._saved)
        self.editor.deleted.connect(self._deleted)
        self.editor.new_requested.connect(self.new_request)
        self.names = NamespacesPanel()
        self.names.picked.connect(self.insert_name)
        self.names.inspected.connect(self.inspect_name)
        self.calendar = SessionCalendar()
        self.calendar.picked.connect(self.insert_date)
        self.calendar.target_picked.connect(self.set_target)
        self.groups = GroupsPane(store)
        self.groups.shown = self.proxy.passes
        self.groups.chosen.connect(self._group_chosen)
        self.groups.dropped.connect(self._set_group)
        self.groups.rescoped.connect(lambda _: self.editor_new_if_empty())
        self.errors = ErrorsPane()
        self.errors.picked.connect(self.show_request)
        # The other way of showing the requests: as cards on a surface, edited in place.
        self.canvas = Canvas(store, self.proxy.passes)
        self.canvas.saved.connect(lambda r, original: self._saved(r, original, self.canvas))
        self.canvas.deleted.connect(self._deleted)
        self.canvas.delete_requested.connect(lambda ids: self.delete_requests(self._requests(ids)))
        self.canvas.moved.connect(self._set_group)

        self._build_toolbar()
        # The filters sit over whichever view is showing, so they move with the view.
        self.filter_bar = QWidget()
        filters = self._build_filters()
        filters.setContentsMargins(0, 0, 0, 0)
        self.filter_bar.setLayout(filters)
        left = QWidget()
        self.table_layout = QVBoxLayout(left)
        self.table_layout.addWidget(self.filter_bar)
        self.table_layout.addWidget(self.table)
        groups_box = QWidget()
        groups_layout = QVBoxLayout(groups_box)
        groups_layout.addWidget(QLabel("Groups"))
        groups_layout.addWidget(self.groups)
        browser = QSplitter()
        browser.addWidget(left)
        browser.addWidget(self.editor)
        browser.setStretchFactor(0, 4)
        browser.setStretchFactor(1, 3)
        canvas_page = QWidget()
        self.canvas_layout = QVBoxLayout(canvas_page)
        self.canvas_layout.addWidget(self.canvas, stretch=1)
        self.views = QStackedWidget()
        self.views.addWidget(browser)
        self.views.addWidget(canvas_page)
        splitter = QSplitter()
        splitter.addWidget(groups_box)
        splitter.addWidget(self.views)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 7)
        self.setCentralWidget(splitter)
        names_dock = QDockWidget("Namespaces", self)
        names_dock.setWidget(self.names)
        self.addDockWidget(Qt.RightDockWidgetArea, names_dock)
        calendar_dock = QDockWidget("Calendar: click to insert, right-click to set target", self)
        calendar_dock.setWidget(self.calendar)
        self.addDockWidget(Qt.RightDockWidgetArea, calendar_dock)
        self.errors_dock = QDockWidget("Errors", self)
        self.errors_dock.setWidget(self.errors)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.errors_dock)
        self._say("Pick a target date and press Reload.")
        self._list_file()
        self.show_view(load_settings().view)
        self.read_calendar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel("Target date "))
        self.date_edit = QDateEdit(QDate(date.today() + timedelta(days=1)))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        # Typed, or set from the calendar pane; a button beside it was only ever misclicked.
        self.date_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        # a finished date, not every keystroke on the way to one
        self.date_edit.editingFinished.connect(self._target_changed)
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
        views = QActionGroup(self)
        self.table_action = toolbar.addAction("Table", lambda: self.show_view(TABLE, True))
        self.canvas_action = toolbar.addAction("Canvas", lambda: self.show_view(CANVAS, True))
        self.table_action.setToolTip("The requests as a table, with the editor beside it")
        self.canvas_action.setToolTip("The requests as cards to zoom around and edit in place")
        for action in (self.table_action, self.canvas_action):
            action.setCheckable(True)
            views.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction("Configure", self.configure)

    @property
    def on_canvas(self) -> bool:
        """Whether the requests are being shown as cards."""
        return self.views.currentIndex() == 1

    def show_view(self, view: str, remember: bool = False) -> None:
        """Show the requests as a table and editor, or as cards on the canvas.

        The filters go with whichever is shown. The choice is kept for the next run when it
        was made on the toolbar.
        """
        canvas = view == CANVAS
        if not canvas and self.on_canvas:
            self.canvas.deactivate()  # save what the card has before the canvas is hidden
        layout = self.canvas_layout if canvas else self.table_layout
        layout.insertWidget(0, self.filter_bar)
        self.views.setCurrentIndex(1 if canvas else 0)
        (self.canvas_action if canvas else self.table_action).setChecked(True)
        if canvas:
            self.canvas.setFocus()
        if remember:
            save_settings(replace(load_settings(), view=view))

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

    def back_up_requests(self) -> None:
        """Copy the requests to Drive, if they have changed since the last copy went.

        The requests are the one thing Puppet Strings keeps that no sheet holds, so a copy of
        them goes where the sheets are. On each load rather than on each save: a snapshot is
        the whole file, and what makes one worth having is that there is a recent one, not
        that it holds the last keystroke. A day that writes no requests sends nothing at all,
        and **Configure → Requests → Back up** takes one whenever it is asked.

        A folder of fixtures carries its own requests and has no Drive to put them on, so it
        takes no backup.
        """
        if self.backup is not None or self.store.fixtures:
            return
        self.backup = Worker(self.store.back_up)
        self.backup.failed.connect(self._backup_failed)
        self.backup.finished.connect(self._backup_finished)
        self.backup.start()

    def _backup_finished(self) -> None:
        self.backup = None

    def _backup_failed(self, why: str) -> None:
        """Say so where the rest of the load's news is, and interrupt nobody.

        Nobody asked for this backup, so a box in front of the day's schedule is the wrong
        way to report it — but it is worth saying, because a Puppet Master who believes there
        are copies on Drive and has none is worse off than one who knows there are none.
        """
        said = self.status_label.text().strip()
        self._say(f"{said} Could not back up the requests: {why.strip().splitlines()[-1]}")

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
        # On, the table is the requests about one date; off, every request in the file.
        self.date_check = QCheckBox("on date")
        self.date_check.setChecked(True)
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
        self.apply_filters()  # the box starts ticked, so the table starts on the date
        return layout

    def apply_filters(self) -> None:
        """Push the filter widgets' state into the proxy model, and recount the groups."""
        self.proxy.set_filters(
            group=self.groups.current,
            text=self.text_filter.text(),
            priority=_choice(self.priority_filter),
            tag=_choice(self.tag_filter),
            staff=_choice(self.staff_filter),
            activity=_choice(self.activity_filter),
            date=self.date_filter.date().toPython() if self.date_check.isChecked() else None,
        )
        self.groups.refresh()
        self.canvas.refresh()

    def show_request(self, request_id: str) -> None:
        """Open a request in the editor, and select its row when the table is showing it.

        On the canvas, the camera goes to its card and opens it.
        """
        if self.on_canvas:
            self.canvas.reveal(request_id)
            return
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
        self.canvas.show_problems(conflicts, errors)
        count = len(conflicts) + len(errors)
        self.errors_dock.setWindowTitle(f"Errors ({count})" if count else "Errors")
        return conflicts, errors

    def _group_chosen(self, group: str) -> None:
        """Show the group the pane switched to. The counts stay: no filter changed."""
        self.proxy.set_filters(group=group)
        if self.on_canvas:
            self.canvas.focus_group(group)
        chosen = "" if group == ALL else f" in {group}"
        self.status_label.setText(f"  {self.proxy.rowCount()} requests{chosen}")

    def _requests(self, ids: list[str]) -> list:
        """The requests with these ids."""
        wanted = set(ids)
        return [r for r in self.store.every if r.id in wanted]

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
        self.editor.clear(group, self.store.group_scopes.of(group) if group else "")

    def _requests_changed(self) -> tuple:
        """The requests moved: the table, both panes and the filters all follow.

        Every way of changing them — saving, deleting, regrouping, loading the offerings —
        ends here, so none of them can forget a pane. Returns the conflicts and the errors
        found, which is what a caller that has just saved something wants to know about.
        """
        self.model.refresh()
        self.groups.refresh()
        self.editor.set_dataset(self.store.dataset, self.store.groups)
        self.canvas.set_dataset(self.store.dataset, self.store.groups)
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

    def _target_changed(self) -> None:
        """Read the day the date box moved to, so no day is shown under another's date.

        Nothing is read before the first Reload, since the day wanted is often not the
        default; after it, the window follows the date. A date that just failed to load is
        not read again on its own: the box finishes editing each time it loses focus, so it
        would fail again at every click, and the way out is to pick another date.
        """
        dataset = self.store.dataset
        if dataset is None or dataset.target == self.target or self.target == self.failed_target:
            return
        if self.loader is not None and self.loader.target == self.target:
            return  # already on its way
        self.reload()

    def set_target(self, day: date) -> None:
        """Make a day the target and read it, as picking it in the date box and reloading does.

        It is asked for outright, so it is read even before the first Reload, and even if it
        failed a moment ago.
        """
        self.date_edit.setDate(QDate(day))
        self.failed_target = None
        dataset = self.store.dataset
        if dataset is not None and dataset.target == day:
            return
        if self.loader is not None and self.loader.target == day:
            return  # already on its way
        self.reload()

    def reload(self) -> None:
        """Read every sheet again for the target date, in the background.

        A click while a load is running queues one more load for when it finishes, and so
        does one while the Adjustments tab is being written, which the load would read.
        """
        if self.loader is not None or self.adjuster is not None:
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

    def read_calendar(self) -> None:
        """Shade and number the calendar on opening, before anything has been loaded.

        The rest waits for Reload, since the day wanted is often not the default, but the
        Calendar sheet is the same whichever day it is and is what you pick the day from.
        A failure says nothing: the first load reads it again and reports properly.
        """
        target = self.target
        self.calendar_reader = Worker(lambda: self.store.calendar(target))
        self.calendar_reader.done.connect(self._calendar_opened)
        self.calendar_reader.finished.connect(self._calendar_reader_finished)
        self.calendar_reader.start()

    def _calendar_opened(self, calendar: dict) -> None:
        """Show it, unless a load has got there first with the day it is about."""
        if self.store.dataset is None and self.loader is None:
            self.calendar.show_calendar(calendar, self.target)

    def _calendar_reader_finished(self) -> None:
        self.calendar_reader = None

    def wait_for_calendar(self) -> None:
        """Block until the calendar read on opening is in (used by tests)."""
        while self.calendar_reader is not None:
            self.calendar_reader.wait()
            QApplication.processEvents()

    def _calendar_read(self, calendar: dict) -> None:
        """Number and shade the calendar as soon as the Calendar sheet itself is read."""
        self.calendar.show_calendar(calendar, self.target)

    def _loaded(self) -> None:
        self.end_progress()
        self.failed_target = None
        if not self.checked_for_updates and getattr(sys, "frozen", False):
            # Once a run, once something has loaded, and only in a copy that was downloaded:
            # a checkout updates with git, so asking GitHub on its behalf is a request sent
            # every time anybody opens the window to no possible end.
            self.checked_for_updates = True
            self.check_for_updates(quietly=True)
        self.back_up_requests()
        dataset = self.store.dataset
        if self.editor.original_id and self.model.request(self.editor.original_id) is None:
            self.new_request()  # the request shown was deleted on the sheet
        self.model.refresh()
        self.table.resizeColumnsToContents()
        self.editor.set_dataset(dataset, self.store.groups)
        self.canvas.set_dataset(dataset, self.store.groups)
        self.groups.refresh()
        self.names.show_dataset(dataset)
        self._fill_combo(self.staff_filter, "any staff", sorted(dataset.staff))
        self._fill_combo(self.activity_filter, "any activity", sorted(dataset.activities))
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self.calendar.show_dataset(dataset)
        self._refresh_same_day()
        self.prefetch_history()
        conflicts, errors = self.refresh_errors()
        self.canvas.refresh()
        today = [a.describe(dataset.staff[a.staff].name) for a in dataset.today_adjustments]
        state = "published" if dataset.baseline is not None else "not published"
        parts = [
            f"Loaded {len(self.store.requests)} requests",
            *([f"imported {self.store.imported} clinics"] if self.store.imported else []),
            f"{dataset.target} is {state}",
            summary(conflicts),
            error_summary(errors),
        ]
        self._say(". ".join(parts + today + list(dataset.warnings)))

    def prefetch_history(self) -> None:
        """Read the published days behind the target, in the background, so Solve is ready.

        Nothing on the window wants them and the solver wants all of them, so they are
        fetched between the two: the load finishes without them and they are usually there
        long before anybody presses Solve. A failure says nothing — the solve reads them
        itself and reports properly if they cannot be had — and a load that starts
        meanwhile makes this answer the wrong day's, which the store drops on arrival.
        """
        if self.store.dataset is None:
            return
        if self.history is not None:
            self.history_wanted = True  # one at a time; this day's turn comes next
            return
        self.history = Worker(self.store.prefetch_history)
        self.history.finished.connect(self._history_finished)
        self.history.start()

    def _history_finished(self) -> None:
        """Drop the thread, and go again if the day changed while it was running."""
        self.history = None
        if self.history_wanted:
            self.history_wanted = False
            self.prefetch_history()

    def wait_for_history(self) -> None:
        """Block until the past days have been read (used by tests)."""
        while self.history is not None:
            self.history.wait()
            QApplication.processEvents()

    def _say(self, message: str) -> None:
        """Put a message in the toolbar, with the whole of it on the tooltip."""
        self.status_label.setText(f"  {message}")
        self.status_label.setToolTip(message)

    def _list_file(self) -> None:
        """Show the requests file with no date loaded: every request, none to be solved."""
        try:
            self.store.list_file()
        except LoadError as e:
            self._say(str(e))
            return
        self.editor.set_dataset(None, self.store.groups)
        self.canvas.set_dataset(None, self.store.groups)
        self.names.show_dataset(None)
        self.model.refresh()
        self._fill_combo(self.tag_filter, "any tag", self.store.tags)
        self.apply_filters()  # which recounts the groups

    def _load_failed(self, message: str) -> None:
        self.failed_target = self.loader.target  # before the box, which takes the focus
        self.end_progress()
        self.status_label.setText("")
        QMessageBox.critical(self, "Could not load", message)

    def _not_a_camp_day(self, message: str) -> None:
        """A date camp is not running is a date to change, not a sheet to go and fix.

        Nothing happens on it, so the table empties of the day it was showing; untick
        "on date" and it lists every request in the file.
        """
        self.failed_target = self.loader.target
        self.end_progress()
        self._list_file()
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
        if not dialog.changed:
            return
        # The store has applied it already: every pane follows, and nothing is read again.
        # The history is fetched again in case the change landed as it arrived and it was
        # dropped as another day's.
        self._requests_changed()
        self.names.show_dataset(self.store.dataset)
        self.prefetch_history()
        if self.loader is not None:
            self.reload_requested = True  # it may have read the tab before this is written
        dataset = self.store.dataset
        today = [a.describe(dataset.staff[a.staff].name) for a in dataset.today_adjustments]
        self._say(". ".join(today) if today else "Nobody is adjusted today")
        self.write_adjustments()

    def write_adjustments(self) -> None:
        """Write the Adjustments tab in the background, one write at a time."""
        if self.adjuster is not None:
            self.adjustments_waiting = True
            return
        self.adjuster = Worker(self.store.adjustments_writer())
        self.adjuster.failed.connect(self._adjustments_failed)
        self.adjuster.finished.connect(self._adjustments_finished)
        self.adjuster.start()

    def wait_for_adjustments(self) -> None:
        """Block until the Adjustments tab has been written (used by tests)."""
        while self.adjuster is not None:
            self.adjuster.wait()
            QApplication.processEvents()

    def _adjustments_failed(self, message: str) -> None:
        """Show what is on the sheet again, since what the window shows never got there."""
        self.adjustments_waiting = False
        self.reload_requested = True  # before the box, which lets the thread finish
        QMessageBox.critical(self, "Could not write the Adjustments tab", message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Let a write of the Adjustments tab land: it is the only copy of what was recorded."""
        if self.adjuster is not None:
            self.adjuster.wait()
            if self.adjustments_waiting:
                self.store.adjustments_writer()()
        super().closeEvent(event)

    def _adjustments_finished(self) -> None:
        """Drop the thread; write again if more was recorded, else run a reload held back."""
        self.adjuster = None
        if self.adjustments_waiting:
            self.adjustments_waiting = False
            self.write_adjustments()
        elif self.reload_requested:
            self.reload_requested = False
            self.reload()

    def load_offerings(self) -> None:
        """Add the Offerings tab's clinics to the day's requests, in the background.

        It reads and may make the day's spreadsheet, so it runs on a worker like the other
        slow jobs: on the UI thread the progress panel would sit there unpainted.
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
        """Open a name from the Namespaces pane: its mapping table, or what it stands for."""
        if self.store.dataset is None:
            return
        if is_mapping(name):
            MappingDialog(self.store.source, self.store.config, name.split(".")[-1], self).exec()
            return
        found = details(name, self.store.dataset)
        if found is not None:
            DetailsDialog(found, self).exec()

    def insert_date(self, day: date) -> None:
        """Put a clicked calendar date into the Skedge editor at the cursor."""
        self.insert_name(day.isoformat())

    def insert_name(self, text: str) -> None:
        """Put a name into whichever Skedge is being written: the editor's, or a card's."""
        (self.canvas if self.on_canvas else self.editor).insert_name(text)

    def run_solve(self) -> None:
        """Solve the target date in the background, then show the schedule dialog."""
        if self.store.dataset is None or self.worker is not None:
            return
        if not self.store.offerings_loaded:
            answer = QMessageBox.question(
                self, "No clinics", f"No clinics imported for {self.target}. Solve anyway?"
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
        solved = self.worker.dataset if self.worker is not None else self.store.current
        ScheduleDialog(self.store.source, self.store.config, solved, result, self).exec()

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

    def _saved(self, request, original_id, editor=None) -> None:
        """Save one request, and leave the editor saying that it is saved.

        `editor` is whichever asked: the request editor, or the canvas for a card.
        """
        editor = editor or self.editor
        if not self._covers_or_agreed(request):
            editor.not_saved("Not saved; still editing")
            self.status_label.setText("  Not saved; still editing")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            saved = self.store.save(request, original_id)
        finally:
            QApplication.restoreOverrideCursor()
        if editor is self.canvas:
            self.canvas.settle(saved)  # the card is filed under its id before the refresh
        if mentions_exclusion(saved.skedge):
            self.reload()  # who is away changes what every other request is read against
            editor.saved_as(saved)
            self.status_label.setText(f"  Saved {saved.id}")
            return
        conflicts, errors = self._requests_changed()
        clashes = [c for c in conflicts if saved.id in c.requests]
        wrong = [e for e in errors if e.request == saved.id]
        note = f"; it conflicts with {len(clashes)} other request(s)" if clashes else ""
        note += f"; {len(wrong)} error(s) in it" if wrong else ""
        editor.saved_as(saved, note)  # last, so nothing else overwrites the confirmation
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
        request = self.model.request(request_id)
        if request is not None:
            self._delete([request])

    def selected_requests(self) -> list:
        """The requests on the selected rows, top to bottom."""
        rows = sorted(self.table.selectionModel().selectedRows(), key=lambda i: i.row())
        found = (self.proxy.data(index, Qt.UserRole) for index in rows)
        return [request for request in found if request is not None]

    def delete_selected(self) -> None:
        """Delete every selected request, once the Puppet Master has said yes."""
        self.delete_requests(self.selected_requests())

    def delete_requests(self, chosen: list) -> None:
        """Delete these requests, once the Puppet Master has said yes."""
        if not chosen:
            return
        shown = "\n".join(r.id for r in chosen[:10])
        if len(chosen) > 10:
            shown += f"\nand {len(chosen) - 10} more"
        many = f"{len(chosen)} requests" if len(chosen) > 1 else "1 request"
        answer = QMessageBox.question(
            self,
            "Delete requests",
            f"Delete {many}?\n\n{shown}",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        if self.editor.original_id in {r.id for r in chosen}:
            self.new_request()  # the one being edited is gone
        self._delete(chosen)

    def _delete(self, requests: list) -> None:
        away = any(mentions_exclusion(r.skedge) for r in requests)
        self.store.delete(*(r.id for r in requests))
        self._requests_changed()
        said = requests[0].id if len(requests) == 1 else f"{len(requests)} requests"
        self.status_label.setText(f"  Deleted {said}")
        if away:
            self.reload()  # the day has somebody back in it, so read it all again

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
