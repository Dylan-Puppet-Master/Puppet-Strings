"""Copy one session's sheets into the trainer's bundled data folder.

    .venv/bin/python tools/snapshot_training.py [--year 2026] [--session 6]

The trainer (`puppet-strings train`) works offline, against a CSV copy of a real session:
its config, skills, clinics, staff categories and cabin act boards. This reads that session
as whoever is signed in to the app, exactly as a load of each of its days would, and
writes every tab it read to `puppet_strings/training/data`, leaving out what the trainer
has no use for: the requests, and the schedules published for each day.
"""

import argparse
import ast
import re
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from puppet_strings.config import load_config  # noqa: E402
from puppet_strings.names import normalize  # noqa: E402
from puppet_strings.session import open_source  # noqa: E402
from puppet_strings.sheets.calendar import parse_calendar  # noqa: E402
from puppet_strings.sheets.load import CABIN_ACTS_FOLDER, load_dataset  # noqa: E402
from puppet_strings.sheets.requests import COLUMNS, REQUESTS_SHEET, SEASON_TAB  # noqa: E402
from puppet_strings.sheets.schedules import ROOT  # noqa: E402
from puppet_strings.sheets.source import CsvSource, LoadError  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "puppet_strings" / "training" / "data"
DROPPED_TABS = {"Assignments", "Staff View", "Clinic View", "Report", "Changes"}


class Recorder:
    """A source that reads through another and writes each tab it reads as CSV.

    Spreadsheets found by walking a folder are known to Drive by id; each is written under
    the folder path it was found at, which is how a `CsvSource` addresses the same one.
    """

    def __init__(self, inner, out: CsvSource) -> None:
        self.inner = inner
        self.out = out
        self.paths: dict[str, str] = {}
        self.cache: dict[tuple[str, str], list] = {}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _path(self, sheet: str) -> str:
        return self.paths.get(sheet, sheet)

    def read(self, sheet, tab):
        """One tab, read once and written as CSV; a published day's tabs are left empty."""
        if tab in DROPPED_TABS:
            self.out.write(self._path(sheet), tab, [])  # a day nobody has solved
            return []
        if (sheet, tab) not in self.cache:
            table = _patiently(lambda: self.inner.read(sheet, tab))
            self.cache[sheet, tab] = table
            if sheet != REQUESTS_SHEET:
                self.out.write(self._path(sheet), tab, table)
        return self.cache[sheet, tab]

    def tabs(self, sheet):
        """A spreadsheet's tab names."""
        return _patiently(lambda: self.inner.tabs(sheet))

    def read_many(self, sheet, tabs):
        """Several tabs of one spreadsheet, each written as CSV."""
        missing = [t for t in tabs if (sheet, t) not in self.cache]
        if missing:
            tables = _patiently(lambda: self.inner.read_many(sheet, missing))
            for tab, table in tables.items():
                self.cache[sheet, tab] = table
                if sheet != REQUESTS_SHEET:
                    self.out.write(self._path(sheet), tab, table)
        return {t: self.cache[sheet, t] for t in tabs}

    def read_all(self, sheets, tab):
        """One tab of each of these spreadsheets."""
        return {title: self.read(key, tab) for title, key in sheets.items()}

    def read_group(self, folder, tab):
        """One tab of every spreadsheet in a folder."""
        return self.read_all(self.group(folder), tab)

    def group(self, folder):
        """Every spreadsheet in a folder, remembering where each goes on disk."""
        found = self.inner.group(folder)
        for title, key in found.items():
            self.paths[key] = f"{folder}/{title}"
        return found

    def documents(self, root, path):
        """The spreadsheets at a path, remembering where each goes on disk."""
        found = self.inner.documents(root, path)
        for title, key in found.items():
            self.paths[key] = "/".join((root, *path, title))
        return found


def _patiently(call):
    """Make a call, waiting out Google's per-minute read quota as often as it takes."""
    for _ in range(10):
        try:
            return call()
        except Exception as e:  # noqa: BLE001 - only the quota is waited out
            if "429" not in str(e):
                raise
            print("  waiting out the read quota")
            time.sleep(30)
    return call()


def _prune_mappings(out: CsvSource, config, day) -> None:
    """Drop the mapping rows that name somebody who was not on staff that session."""
    config = replace(config, folders={"root": ROOT, "cabin_acts": CABIN_ACTS_FOLDER})
    while True:
        try:
            load_dataset(out, config, day, history=False)
            return
        except LoadError as e:
            found = re.match(r"Mappings/(\w+) row (\[.*?\]):", str(e))
            if not found:
                raise
            tab, row = found.group(1), ast.literal_eval(found.group(2))
            table = out.read("config", tab)
            kept = [r for r in table if [normalize(c) for c in r[: len(row)]] != row]
            print(f"  dropped {tab} row {row}")
            out.write("config", tab, kept)


def main() -> int:
    """Snapshot the session named on the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--session", type=int, default=6)
    args = parser.parse_args()
    config = load_config()
    if OUT.exists():
        shutil.rmtree(OUT)
    out = CsvSource(OUT)
    source = Recorder(open_source(config, None), out)
    source.discover(ROOT, args.year)
    calendar = source.read("config", config.tabs["calendar"])
    spans = parse_calendar(calendar, config.date_order)
    span = next(s for s in spans if s.session == args.session and s.start.year == args.year)
    for day in span.dates:
        print(f"reading {day}")
        try:
            load_dataset(source, config, day, history=False)
        except LoadError as e:
            # The mappings are checked last, against whoever is on staff that day, and the
            # live ones are kept for the session being run now; everything was read by then.
            print(f"  {e}")
    out.write(REQUESTS_SHEET, SEASON_TAB, [list(COLUMNS)])
    _prune_mappings(out, config, span.dates[0])
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
