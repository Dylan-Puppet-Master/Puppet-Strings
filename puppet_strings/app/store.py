"""The app's copy of the requests, loaded from and saved to the requests file."""

from dataclasses import replace
from datetime import date
from itertools import count

from puppet_strings.app.conflicts import Conflict, find_conflicts
from puppet_strings.app.errors import Problem, find_errors
from puppet_strings.app.facets import Facets, resolve_request
from puppet_strings.app.group_tabs import GroupTabs
from puppet_strings.app.groups import DEFAULT_GROUPS, clean, same_group
from puppet_strings.config import Config
from puppet_strings.exclude import apply_exclusions
from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Adjustment, Dataset, Request, Rest
from puppet_strings.names import normalize
from puppet_strings.publish.writer import day_sheet
from puppet_strings.requests_db import (
    CLINICS_SUFFIX,
    SEASON,
    SPECIAL_SUFFIX,
    clinics_list,
    home_for,
    open_requests,
)
from puppet_strings.sheets.adjustments import adjustment_rows
from puppet_strings.sheets.calendar import calendar_days, parse_calendar
from puppet_strings.sheets.load import load_dataset, read_history
from puppet_strings.sheets.schedules import ROOT
from puppet_strings.sheets.source import CsvSource, Source

CONFIG_SHEET = "config"


def unique_id(home: str, taken: set[str]) -> str:
    """The next free id in a list: `s4-1`, `s4-2`, `season-1`.

    The id is not made out of the description any more. A description is for people, is
    allowed to be empty, and gets rewritten the moment somebody words it better — none of
    which an id may do, because it is what the solver's report and every other sheet call
    the request by.

    Numbering runs per list because a load only ever reads three of them: the season's and
    the two of the span being scheduled. An id carrying the list it was made in can only
    collide with the ids of that same list, which is either loaded or is the season's, and
    the season's is always loaded.
    """
    base = normalize(_label(home)).strip("_").replace("_", "-") or "request"
    numbers = {int(i[len(base) + 1 :]) for i in taken if _numbered(i, base)}
    return f"{base}-{next(n for n in count(1) if n not in numbers)}"


def _label(home: str) -> str:
    """What a list's ids are named after: `S4 Special` and `S4 Clinics` are both `s4`."""
    for suffix in (SPECIAL_SUFFIX, CLINICS_SUFFIX):
        if home.endswith(suffix):
            return home[: -len(suffix)]
    return "season" if home == SEASON else home


def _numbered(request_id: str, base: str) -> bool:
    """Whether an id is one of this list's numbered ones."""
    return request_id.startswith(f"{base}-") and request_id[len(base) + 1 :].isdigit()


class RequestStore:
    """Requests plus the dataset they are validated against."""

    def __init__(self, source: Source, config: Config) -> None:
        self.source = source
        self.config = config
        self.book = open_requests(config, source)
        self.dataset: Dataset | None = None
        self.requests: list[Request] = []
        self.facets: dict[str, Facets] = {}
        self.resolved: dict[str, tuple] = {}  # each request's copies, for the conflict finder
        # A group lives on the requests in it, so one just made holds nothing yet and would
        # vanish on the next read. These keep it in the pane until something joins it.
        self.empty_groups: list[str] = []
        self.held: set[str] = set()  # the request lists the load read, home or not
        self.group_tabs = GroupTabs()  # which list each group's new requests go to

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
        """
        self.dataset = load_dataset(
            self.source, self.config, target, history=False, requests=self.book
        )
        self.requests = list(self.dataset.requests)
        # the lists this load read, so one emptied by a deletion is written empty
        self.held = {r.home for r in self.requests if r.home}
        self.facets, self.resolved = {}, {}
        for request in self.requests:
            self._index(request)

    def _index(self, request: Request) -> None:
        """Work out what one request means: its facets, and the copies it resolves to."""
        self.facets[request.id], self.resolved[request.id] = resolve_request(request, self.dataset)

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
        """Add or replace a request and write the lists it and its neighbours are in.

        A request without an id gets the next one free in its list, and one that names no
        list goes to this span's Special list — or its Clinics list, if it was generated.
        Returns the request as saved.
        """
        request = replace(
            request, home=home_for(request, self.dataset.this_span, self.dataset.target)
        )
        ids = [r.id for r in self.requests]
        if original_id in ids:
            request = replace(request, id=original_id)
            self.requests[ids.index(original_id)] = request
        else:
            if not request.id:
                request = replace(request, id=unique_id(request.home, set(ids)))
            self.requests.append(request)
        self._index(request)
        self._write()
        return request

    def load_offerings(self) -> int:
        """Replace the date's generated requests with the Offerings tab's. Returns how many.

        The day's spreadsheet is made first if it is not there yet, with the Offerings grid
        to fill in and the views a solve will write, so a new day is one click from being
        ready rather than a folder to go and build by hand.
        """
        day_sheet(self.source, self.config, self.dataset.this_span, self.dataset.target)
        generated = generated_requests(self.dataset, home=clinics_list(self.dataset.target))
        self.requests = merge(self.requests, generated, self.dataset.target)
        self._reindex(generated)
        self._write()
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
        return sorted({t for r in self.requests for t in r.tags})

    @property
    def groups(self) -> list[str]:
        """Every group there is: the default ones first, then the rest alphabetically.

        A group is whatever some request says it is in, plus the ones made in the app that
        nothing has joined yet.
        """
        known = list(DEFAULT_GROUPS)
        for name in [r.group for r in self.requests if r.group] + self.empty_groups:
            if not any(same_group(name, seen) for seen in known):
                known.append(name)
        return known[: len(DEFAULT_GROUPS)] + sorted(known[len(DEFAULT_GROUPS) :], key=str.lower)

    def count(self, group: str) -> int:
        """How many requests are on a shelf."""
        return sum(1 for r in self.requests if same_group(group, r.group))

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
        self.group_tabs.rename(old, new)
        self._regroup(lambda group: new if same_group(old, group) else group)
        return new

    def delete_group(self, name: str) -> None:
        """Take the shelf away; the requests that were on it stay, on none."""
        self.empty_groups = [g for g in self.empty_groups if not same_group(name, g)]
        self.group_tabs.forget(name)
        self._regroup(lambda group: "" if same_group(name, group) else group)

    def set_group(self, request_ids: list[str], group: str) -> None:
        """Move requests onto a shelf, off whichever one they were on. "" takes them off."""
        wanted = set(request_ids)
        self.requests = [replace(r, group=group) if r.id in wanted else r for r in self.requests]
        if group:
            self.empty_groups = [g for g in self.empty_groups if not same_group(group, g)]
        self._write()

    def _regroup(self, change) -> None:
        """Rewrite every request's group, and the sheet, if anything moved."""
        rewritten = [replace(r, group=change(r.group)) for r in self.requests]
        if rewritten != self.requests:
            self.requests = rewritten
            self._write()

    def delete(self, *request_ids: str) -> None:
        """Remove requests, however many, and write their lists once."""
        gone = set(request_ids)
        self.requests = [r for r in self.requests if r.id not in gone]
        for request_id in gone:
            self.facets.pop(request_id, None)
            self.resolved.pop(request_id, None)
        self._write()

    def _write(self) -> None:
        """Write each request to its list, and empty any list left with none."""
        self.held |= {r.home for r in self.requests if r.home}
        self.book.write(tuple(self.requests), self.held)
