"""The app's copy of the requests, loaded from and saved to the requests file."""

from dataclasses import replace
from datetime import date

from puppet_strings.app.conflicts import Conflict, find_conflicts
from puppet_strings.app.errors import Problem, find_errors
from puppet_strings.app.facets import Facets, resolve_request
from puppet_strings.app.group_scopes import GroupScopes
from puppet_strings.app.groups import DEFAULT_GROUPS, clean, same_group
from puppet_strings.config import Config
from puppet_strings.exclude import apply_exclusions
from puppet_strings.generate import (
    generated_requests,
    has_offerings_loaded,
    import_if_missing,
    is_generated,
    merge,
)
from puppet_strings.model import Adjustment, Dataset, Request, Rest
from puppet_strings.publish.writer import day_sheet
from puppet_strings.requests_db import id_prefix, open_requests, scope_for
from puppet_strings.sheets.adjustments import adjustment_rows
from puppet_strings.sheets.calendar import calendar_days, parse_calendar
from puppet_strings.sheets.load import load_dataset, read_history
from puppet_strings.sheets.schedules import ROOT
from puppet_strings.sheets.source import CsvSource, Source

CONFIG_SHEET = "config"


class RequestStore:
    """Requests plus the dataset they are validated against."""

    def __init__(self, source: Source, config: Config) -> None:
        self.source = source
        self.config = config
        self.book = open_requests(config, source)
        self.dataset: Dataset | None = None
        self.imported = 0  # clinics the last load imported from the Offerings tab
        self.requests: list[Request] = []  # the ones read on the target date, and so solved
        # Everything else in the file, scoped to other dates: listed, never solved. Their
        # facets are worked out when a filter first asks, since a season holds hundreds.
        self.elsewhere: list[Request] = []
        self.facets: dict[str, Facets] = {}
        self.resolved: dict[str, tuple] = {}  # each request's copies, for the conflict finder
        # A group lives on the requests in it, so one just made holds nothing yet and would
        # vanish on the next read. These keep it in the pane until something joins it.
        self.empty_groups: list[str] = []
        self.group_scopes = GroupScopes()  # the scope each group's new requests take

    @property
    def fixtures(self) -> bool:
        """Whether these are CSV files on disk rather than Google Sheets."""
        return isinstance(self.source, CsvSource)

    @property
    def credentials(self) -> object | None:
        """What the sheets are being read as, for the Configure pane to name."""
        return getattr(self.source, "credentials", None)

    def reconnect(self, source: Source, config: Config) -> None:
        """Read different sheets from now on, the Configure pane having changed which."""
        self.source, self.config = source, config
        self.book = open_requests(config, source)

    def calendar(self, target: date) -> dict:
        """The Calendar sheet on its own: every camp day, its span, session and week.

        One tab, read without any of the rest, so the calendar pane can number its weeks
        while the load that would fill it is still running — or after one has failed on a
        sheet that has nothing to do with the calendar.
        """
        self.source.discover(ROOT, target.year)
        table = self.source.read(CONFIG_SHEET, self.config.tabs["calendar"])
        return calendar_days(parse_calendar(table, self.config.date_order))

    def load(self, target: date) -> None:
        """Read every sheet for a target date. Raises LoadError.

        Not the days behind it, though: what was published on them is the solver's
        business, nothing in the window asks, and there is a spreadsheet of them per day of
        the season so far. `for_solving` reads them when something is about to want them.

        A date with no clinics imported yet has its Offerings tab imported on the way in;
        `imported` says how many, for the window to report.
        """
        dataset = load_dataset(self.source, self.config, target, history=False, requests=self.book)
        self.dataset, self.imported = import_if_missing(dataset, self.book)
        self.requests = list(self.dataset.requests)
        here = {r.id for r in self.requests}
        self.elsewhere = [r for r in self.book.every() if r.id not in here]
        self.facets, self.resolved = {}, {}
        for request in self.requests:
            self._index(request)

    def list_file(self) -> None:
        """With no date loaded, hold every request in the file, none of them to be solved.

        The file is on this computer, so listing it needs no sheets: before the first load,
        or after a date camp is not running, the table can still show everything there is.
        Raises LoadError for a file this version cannot read.
        """
        self.dataset, self.imported = None, 0
        self.requests, self.elsewhere = [], list(self.book.every())
        self.facets, self.resolved = {}, {}

    def _index(self, request: Request) -> None:
        """Work out what one request means: its facets, and the copies it resolves to."""
        self.facets[request.id], self.resolved[request.id] = resolve_request(request, self.dataset)

    @property
    def every(self) -> list[Request]:
        """Every request in the file: the target date's first, then the rest."""
        return self.requests + self.elsewhere

    def facet(self, request: Request) -> Facets:
        """What the filters need to know about a request, worked out the first time it is asked.

        One scoped to other dates is read against the target date's sheets, which is as near
        as the window can get without loading its own day.
        """
        if request.id not in self.facets:
            self.facets[request.id] = resolve_request(request, self.dataset)[0]
        return self.facets[request.id]

    @property
    def conflicts(self) -> tuple[Conflict, ...]:
        """Where the requests contradict each other, read off the resolved copies."""
        if self.dataset is None:
            return ()
        return find_conflicts(self.requests, self.resolved, self.dataset)

    @property
    def errors(self) -> tuple[Problem, ...]:
        """Where one request on its own asks for something the sheets rule out."""
        if self.dataset is None:
            return ()
        return find_errors(self.requests, self.resolved, self.dataset)

    def save(self, request: Request, original_id: str | None) -> Request:
        """Add or replace a request, and write it. Returns the request as saved.

        One with no scope is scoped to this session, or to this day if it was generated. A
        new one gets the next id free in the whole file for its scope — `s4-3`, `jun08-1`,
        `season-2` — rather than one made of its description: a description is for people,
        may be empty and gets reworded, none of which the name the report uses may do.
        """
        request = replace(request, scope=scope_for(request, self.dataset))
        if original_id in {r.id for r in self.every}:
            request = replace(request, id=original_id)
        elif not request.id:
            prefix = id_prefix(request.scope, self.dataset)
            request = replace(request, id=self.book.next_id(prefix))
        # a request scoped away from the target date is listed but not solved
        here = request.scope.covers(self.dataset.target)
        self.requests = _placed(self.requests, request, original_id, here)
        self.elsewhere = _placed(self.elsewhere, request, original_id, not here)
        self.facets.pop(request.id, None)
        self.resolved.pop(request.id, None)
        if here:
            self._index(request)
        self.book.put([request])
        return request

    def load_offerings(self) -> int:
        """Replace the date's generated requests with the Offerings tab's. Returns how many.

        The day's spreadsheet is made first if it is not there yet, with the Offerings grid
        to fill in and the views a solve will write, so a new day is one click from being
        ready rather than a folder to go and build by hand.
        """
        target = self.dataset.target
        day_sheet(self.source, self.config, self.dataset.this_span, target)
        generated = generated_requests(self.dataset)
        old = [r.id for r in self.requests if is_generated(r, target)]
        self.requests = merge(self.requests, generated, target)
        self._reindex(generated)
        self.book.delete(old)
        self.book.put(generated)
        return len(generated)

    def _reindex(self, added: list[Request]) -> None:
        """Forget what the requests just dropped meant, and work out what the new ones do."""
        kept = {r.id for r in self.requests}
        self.facets = {i: f for i, f in self.facets.items() if i in kept}
        self.resolved = {i: c for i, c in self.resolved.items() if i in kept}
        for request in added:
            self._index(request)

    @property
    def current(self) -> Dataset:
        """The loaded dataset with the requests as they are now, saved edits included.

        An EXCLUDE among those edits is applied here, so the schedule that is solved, the
        views that show it and the sheet it is published to all agree about who is away.
        """
        return apply_exclusions(replace(self.dataset, requests=tuple(self.requests)))

    def resolutions(self):
        """The copies each request of the day resolved to, for a solve to use again."""
        from puppet_strings.solver.solve import Resolutions

        copies = {r.id: (r, self.resolved[r.id]) for r in self.requests if r.id in self.resolved}
        return Resolutions(self.dataset, copies)

    def for_solving(self) -> Dataset:
        """The current dataset with the published days behind the target read into it.

        Called off the UI thread, on the way into a solve. Where the prefetch has already
        read them, this costs nothing and Solve starts straight away.
        """
        return read_history(self.source, self.config, self.current)

    def prefetch_history(self) -> bool:
        """Read the days behind the target into the loaded dataset. For a worker thread.

        The window does not need them, so a load does not wait for them; a solve does, so
        they are fetched while the Puppet Master reads the day over. Returns whether they
        landed.

        The dataset they were asked for is the dataset they are put into, and nothing else:
        a load started since has read another day, and yesterday's answer is no part of it.
        A Dataset is frozen and swapping one for another is a single assignment, so a reader
        on the other thread sees the whole of one or the whole of the other.
        """
        asked_for = self.dataset
        if asked_for is None or asked_for.published:
            return False
        filled = read_history(self.source, self.config, asked_for)
        if self.dataset is not asked_for:
            return False
        self.dataset = filled
        return True

    @property
    def offerings_loaded(self) -> bool:
        """Whether generated requests exist for the target date."""
        return has_offerings_loaded(tuple(self.requests), self.dataset.target)

    def set_adjustment(
        self,
        staff_id: str,
        resting: Rest | None = None,
        penalty: int | None = None,
        note: str = "",
    ) -> None:
        """Record what changed for one staff member today.

        Only the fields given are set, so a sleep agreement and a rest can be recorded
        one after the other without either wiping the other.
        """
        target = self.dataset.target
        rows = {(a.date, a.staff): a for a in self.dataset.adjustments}
        current = rows.get((target, staff_id), Adjustment(target, staff_id))
        rows[target, staff_id] = replace(
            current,
            resting=current.resting if resting is None else resting,
            ral_penalty=current.ral_penalty if penalty is None else penalty,
            note=note or current.note,
        )
        self._write_adjustments(list(rows.values()))

    def clear_adjustment(self, staff_id: str) -> None:
        """Put one staff member back to their usual standing for today."""
        target = self.dataset.target
        kept = [a for a in self.dataset.adjustments if (a.date, a.staff) != (target, staff_id)]
        self._write_adjustments(kept)

    def _write_adjustments(self, adjustments: list[Adjustment]) -> None:
        """Write the tab and keep the dataset in step, so the dialog shows what it wrote.

        The staff themselves are only re-read on the next load, which is why the window
        reloads once the dialog closes.
        """
        tab = self.config.tabs["adjustments"]
        self.source.write(
            CONFIG_SHEET, tab, adjustment_rows(tuple(adjustments), self.dataset.staff)
        )
        self.dataset = replace(self.dataset, adjustments=tuple(adjustments))

    @property
    def tags(self) -> list[str]:
        """Every tag in use, sorted."""
        return sorted({t for r in self.every for t in r.tags})

    @property
    def groups(self) -> list[str]:
        """Every group there is: the default ones first, then the rest alphabetically.

        A group is whatever some request says it is in, plus the ones made in the app that
        nothing has joined yet.
        """
        known = list(DEFAULT_GROUPS)
        for name in [r.group for r in self.every if r.group] + self.empty_groups:
            if not any(same_group(name, seen) for seen in known):
                known.append(name)
        return known[: len(DEFAULT_GROUPS)] + sorted(known[len(DEFAULT_GROUPS) :], key=str.lower)

    def count(self, group: str) -> int:
        """How many requests are on a shelf."""
        return sum(1 for r in self.every if same_group(group, r.group))

    def add_group(self, name: str) -> str:
        """Make a group. Returns the name it settled on, or "" if it is not a new one."""
        name = clean(name)
        if not name or any(same_group(name, known) for known in self.groups):
            return ""
        self.empty_groups.append(name)
        return name

    def rename_group(self, old: str, new: str) -> str:
        """Rename a group everywhere it appears. Returns the new name, or "" if refused."""
        new = clean(new)
        taken = [g for g in self.groups if not same_group(old, g)]
        if not new or new == old or any(same_group(new, known) for known in taken):
            return ""
        self.empty_groups = [new if same_group(old, g) else g for g in self.empty_groups]
        self.group_scopes.rename(old, new)
        self._regroup(lambda group, _: new if same_group(old, group) else group)
        return new

    def delete_group(self, name: str) -> None:
        """Take the shelf away; the requests that were on it stay, on none."""
        self.empty_groups = [g for g in self.empty_groups if not same_group(name, g)]
        self.group_scopes.forget(name)
        self._regroup(lambda group, _: "" if same_group(name, group) else group)

    def set_group(self, request_ids: list[str], group: str) -> None:
        """Move requests onto a shelf, off whichever one they were on. "" takes them off."""
        wanted = set(request_ids)
        if group:
            self.empty_groups = [g for g in self.empty_groups if not same_group(group, g)]
        self._regroup(lambda was, r: group if r.id in wanted else was)

    def _regroup(self, change) -> None:
        """Give each request the group `change(group, request)` says; write those that moved."""
        requests = [replace(r, group=change(r.group, r)) for r in self.requests]
        elsewhere = [replace(r, group=change(r.group, r)) for r in self.elsewhere]
        moved = [
            new for new, was in zip(requests + elsewhere, self.every, strict=True) if new != was
        ]
        self.requests, self.elsewhere = requests, elsewhere
        self.book.put(moved)

    def delete(self, *request_ids: str) -> None:
        """Remove requests, however many."""
        gone = set(request_ids)
        self.requests = [r for r in self.requests if r.id not in gone]
        self.elsewhere = [r for r in self.elsewhere if r.id not in gone]
        for request_id in gone:
            self.facets.pop(request_id, None)
            self.resolved.pop(request_id, None)
        self.book.delete(gone)


def _placed(requests: list[Request], request: Request, original_id: str | None, wanted: bool):
    """The list with `request` in the place of `original_id`, at the end, or taken out.

    A request stays where it was in the list it was already on, and a new one goes last.
    """
    at = next((i for i, r in enumerate(requests) if r.id in (original_id, request.id)), None)
    if not wanted:
        return requests if at is None else requests[:at] + requests[at + 1 :]
    if at is None:
        return [*requests, request]
    return [*requests[:at], request, *requests[at + 1 :]]
