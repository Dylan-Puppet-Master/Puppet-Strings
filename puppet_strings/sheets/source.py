"""Where tables come from: Google Sheets through gspread, or CSV files on disk.

A table is a list of rows, each a list of cell strings, exactly as a sheet holds it.
Parsers never touch this module; they take tables.
"""

import csv
from pathlib import Path
from typing import Protocol

Table = list[list[str]]


class LoadError(Exception):
    """Bad or missing sheet data. The message names the sheet, tab, and cell or row."""


class Source(Protocol):
    """A collection of named spreadsheets, each a collection of named tabs."""

    def tabs(self, sheet: str) -> list[str]:
        """Tab names in a spreadsheet."""

    def read(self, sheet: str, tab: str) -> Table:
        """All cells of a tab. Missing tab raises LoadError."""

    def read_many(self, sheet: str, tabs: list[str]) -> dict[str, Table]:
        """Several tabs of one spreadsheet, in as few requests as possible."""

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Replace a tab's contents, creating the tab if needed."""


class CsvSource:
    """Tables stored as `<root>/<sheet>/<tab>.csv`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def tabs(self, sheet: str) -> list[str]:
        """Tab names, from the CSV file names."""
        folder = self.root / sheet
        if not folder.is_dir():
            raise LoadError(f"{sheet}: no folder {folder}")
        return sorted(p.stem for p in folder.glob("*.csv"))

    def read(self, sheet: str, tab: str) -> Table:
        """Rows of one CSV file."""
        path = self.root / sheet / f"{tab}.csv"
        if not path.exists():
            raise LoadError(f"{sheet}: no tab '{tab}' ({path} missing)")
        with path.open(newline="", encoding="utf-8") as f:
            return [list(row) for row in csv.reader(f)]

    def read_many(self, sheet: str, tabs: list[str]) -> dict[str, Table]:
        """Each tab's rows."""
        return {tab: self.read(sheet, tab) for tab in tabs}

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Write one CSV file."""
        path = self.root / sheet / f"{tab}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(table)


class SheetsSource:
    """Tables read from Google Sheets with a service account.

    Every API call takes a noticeable fraction of a second, so tab lists are cached per
    spreadsheet and `read_many` fetches all the tabs it is asked for in one request.
    """

    def __init__(self, sheet_ids: dict[str, str], credentials: Path) -> None:
        import gspread

        self.client = gspread.service_account(filename=str(credentials))
        self.sheet_ids = sheet_ids
        self._open: dict[str, object] = {}
        self._tabs: dict[str, list[str]] = {}

    def _spreadsheet(self, sheet: str):
        if sheet not in self.sheet_ids:
            raise LoadError(f"{sheet}: no spreadsheet id in config.toml [sheets]")
        if sheet not in self._open:
            self._open[sheet] = self.client.open_by_key(self.sheet_ids[sheet])
        return self._open[sheet]

    def tabs(self, sheet: str) -> list[str]:
        """Worksheet titles, fetched once per spreadsheet."""
        if sheet not in self._tabs:
            self._tabs[sheet] = [ws.title for ws in self._spreadsheet(sheet).worksheets()]
        return self._tabs[sheet]

    def read(self, sheet: str, tab: str) -> Table:
        """All values of one worksheet."""
        return self.read_many(sheet, [tab])[tab]

    def read_many(self, sheet: str, tabs: list[str]) -> dict[str, Table]:
        """All values of several worksheets in one request."""
        if not tabs:
            return {}
        missing = [tab for tab in tabs if tab not in self.tabs(sheet)]
        if missing:
            raise LoadError(f"{sheet}: no tab {', '.join(repr(t) for t in missing)}")
        ranges = [f"'{tab}'" for tab in tabs]
        response = self._spreadsheet(sheet).values_batch_get(ranges)
        tables = {}
        for tab, value_range in zip(tabs, response.get("valueRanges", []), strict=True):
            tables[tab] = [list(row) for row in value_range.get("values", [])]
        return tables

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Clear and refill a worksheet, adding it if missing."""
        import gspread

        spreadsheet = self._spreadsheet(sheet)
        try:
            worksheet = spreadsheet.worksheet(tab)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(tab, rows=max(len(table), 1), cols=26)
            self._tabs.pop(sheet, None)
        if table:
            worksheet.update(table, "A1")


def header_rows(table: Table, required: tuple[str, ...], where: str) -> list[dict[str, str]]:
    """Rows as dicts keyed by the (stripped) header row. Blank rows are dropped."""
    if not table:
        raise LoadError(f"{where}: empty tab")
    header = [cell.strip() for cell in table[0]]
    missing = [name for name in required if name not in header]
    if missing:
        raise LoadError(f"{where}: missing columns {missing}; header is {header}")
    rows = []
    for cells in table[1:]:
        if not any(cell.strip() for cell in cells):
            continue
        padded = cells + [""] * (len(header) - len(cells))
        rows.append({name: value.strip() for name, value in zip(header, padded, strict=False)})
    return rows


def parse_int(value: str, where: str) -> int:
    """An integer cell, or a LoadError naming the cell."""
    try:
        return int(value)
    except ValueError as e:
        raise LoadError(f"{where}: expected a whole number, got '{value}'") from e


def split_list(value: str) -> list[str]:
    """A comma-separated cell as a list of stripped items."""
    return [item.strip() for item in value.split(",") if item.strip()]
