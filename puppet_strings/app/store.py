"""The app's copy of the requests, loaded from and saved to the Requests sheet."""

from datetime import date

from puppet_strings.app.facets import Facets, facets
from puppet_strings.config import Config
from puppet_strings.model import Dataset, Request
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.requests import request_rows
from puppet_strings.sheets.source import Source

CONFIG_SHEET = "config"


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

    def save(self, request: Request, original_id: str | None) -> None:
        """Add or replace a request and write the whole Requests tab."""
        ids = [r.id for r in self.requests]
        if original_id in ids:
            self.requests[ids.index(original_id)] = request
            if original_id != request.id:
                self.facets.pop(original_id, None)
        else:
            self.requests.append(request)
        self.facets[request.id] = facets(request, self.dataset)
        self._write()

    def delete(self, request_id: str) -> None:
        """Remove a request and write the Requests tab."""
        self.requests = [r for r in self.requests if r.id != request_id]
        self.facets.pop(request_id, None)
        self._write()

    def _write(self) -> None:
        tab = self.config.tabs["requests"]
        self.source.write(CONFIG_SHEET, tab, request_rows(tuple(self.requests)))
