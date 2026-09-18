"""The app's copy of the requests, loaded from and saved to the Requests sheet."""

from dataclasses import replace
from datetime import date

from puppet_strings.app.conflicts import Conflict, find_conflicts
from puppet_strings.app.facets import Facets, resolve_request
from puppet_strings.app.groups import DEFAULT_GROUPS, clean, same_group
from puppet_strings.config import Config
from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Adjustment, Dataset, Request, Rest
from puppet_strings.names import normalize
from puppet_strings.sheets.adjustments import adjustment_rows
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.requests import request_rows
from puppet_strings.sheets.source import Source

CONFIG_SHEET = "config"


def unique_id(description: str, taken: set[str]) -> str:
    """A readable id from the description: "Dylan's day off" -> dylan-s-day-off, -2, -3..."""
    base = normalize(description)[:40].strip("_").replace("_", "-") or "request"
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


class RequestStore:
    """Requests plus the dataset they are validated against."""

    def __init__(self, source: Source, config: Config) -> None:
        self.source = source
        self.config = config
        self.dataset: Dataset | None = None
        self.requests: list[Request] = []
        self.facets: dict[str, Facets] = {}
        self.resolved: dict[str, tuple] = {}  # each request's copies, for the conflict finder
        # A group lives on the requests in it, so one just made holds nothing yet and would
        # vanish on the next read. These keep it in the pane until something joins it.
        self.empty_groups: list[str] = []

    def load(self, target: date) -> None:
        """Read every sheet for a target date. Raises LoadError."""
        self.dataset = load_dataset(self.source, self.config, target)
        self.requests = list(self.dataset.requests)
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

    def save(self, request: Request, original_id: str | None) -> Request:
        """Add or replace a request and write the whole Requests tab.

        A request without an id gets one made from its description. Returns the request
        as saved.
        """
        ids = [r.id for r in self.requests]
        if original_id in ids:
            request = replace(request, id=original_id)
            self.requests[ids.index(original_id)] = request
        else:
            if not request.id:
                request = replace(request, id=unique_id(request.description, set(ids)))
            self.requests.append(request)
        self._index(request)
        self._write()
        return request

    def load_offerings(self) -> int:
        """Replace the date's generated requests with the Offerings tab's. Returns how many."""
        generated = generated_requests(self.dataset)
        self.requests = merge(self.requests, generated, self.dataset.target)
        kept = {r.id for r in self.requests}
        self.facets = {i: f for i, f in self.facets.items() if i in kept}
        self.resolved = {i: c for i, c in self.resolved.items() if i in kept}
        for request in generated:
            self._index(request)
        self._write()
        return len(generated)

    @property
    def current(self) -> Dataset:
        """The loaded dataset with the requests as they are now, saved edits included."""
        return replace(self.dataset, requests=tuple(self.requests))

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
        for name in [g for r in self.requests for g in r.groups] + self.empty_groups:
            if not any(same_group(name, seen) for seen in known):
                known.append(name)
        return known[: len(DEFAULT_GROUPS)] + sorted(known[len(DEFAULT_GROUPS) :], key=str.lower)

    def count(self, group: str) -> int:
        """How many requests are in a group."""
        return sum(1 for r in self.requests if any(same_group(group, g) for g in r.groups))

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
        self._regroup(lambda groups: tuple(new if same_group(old, g) else g for g in groups))
        return new

    def delete_group(self, name: str) -> None:
        """Remove a group from every request that is in it."""
        self.empty_groups = [g for g in self.empty_groups if not same_group(name, g)]
        self._regroup(lambda groups: tuple(g for g in groups if not same_group(name, g)))

    def set_group(self, request_ids: list[str], group: str, member: bool) -> None:
        """Put requests into a group or take them out of it."""
        wanted = set(request_ids)

        def change(request: Request) -> tuple[str, ...]:
            groups = tuple(g for g in request.groups if not same_group(group, g))
            return groups + (group,) if member else groups

        self.requests = [
            replace(r, groups=change(r)) if r.id in wanted else r for r in self.requests
        ]
        if member:
            self.empty_groups = [g for g in self.empty_groups if not same_group(group, g)]
        self._write()

    def _regroup(self, change) -> None:
        """Rewrite every request's groups, and the sheet, if anything moved."""
        rewritten = [replace(r, groups=change(r.groups)) for r in self.requests]
        if rewritten != self.requests:
            self.requests = rewritten
            self._write()

    def delete(self, request_id: str) -> None:
        """Remove a request and write the Requests tab."""
        self.requests = [r for r in self.requests if r.id != request_id]
        self.facets.pop(request_id, None)
        self.resolved.pop(request_id, None)
        self._write()

    def _write(self) -> None:
        tab = self.config.tabs["requests"]
        self.source.write(CONFIG_SHEET, tab, request_rows(tuple(self.requests)))
