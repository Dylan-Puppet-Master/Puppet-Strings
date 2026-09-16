"""The app's copy of the requests, loaded from and saved to the Requests sheet."""

from dataclasses import replace
from datetime import date

from puppet_strings.app.facets import Facets, facets
from puppet_strings.config import Config
from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Adjustment, Dataset, Request
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

    def load(self, target: date) -> None:
        """Read every sheet for a target date. Raises LoadError."""
        self.dataset = load_dataset(self.source, self.config, target)
        self.requests = list(self.dataset.requests)
        self.facets = {r.id: facets(r, self.dataset) for r in self.requests}

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
        self.facets[request.id] = facets(request, self.dataset)
        self._write()
        return request

    def load_offerings(self) -> int:
        """Replace the date's generated requests with the Offerings tab's. Returns how many."""
        generated = generated_requests(self.dataset)
        self.requests = merge(self.requests, generated, self.dataset.target)
        self.facets = {r.id: f for r, f in ((r, self.facets.get(r.id)) for r in self.requests) if f}
        for request in generated:
            self.facets[request.id] = facets(request, self.dataset)
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

    def set_adjustment(self, staff_id: str, available: bool, ral: int | None, note: str) -> None:
        """Record what changed for one staff member today, replacing any earlier row."""
        target = self.dataset.target
        kept = [a for a in self.dataset.adjustments if (a.date, a.staff) != (target, staff_id)]
        adjustment = Adjustment(target, staff_id, available, ral, note)
        self._write_adjustments([*kept, adjustment])

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

    def delete(self, request_id: str) -> None:
        """Remove a request and write the Requests tab."""
        self.requests = [r for r in self.requests if r.id != request_id]
        self.facets.pop(request_id, None)
        self._write()

    def _write(self) -> None:
        tab = self.config.tabs["requests"]
        self.source.write(CONFIG_SHEET, tab, request_rows(tuple(self.requests)))
