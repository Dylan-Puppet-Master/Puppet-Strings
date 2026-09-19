"""Where tables come from: Google Sheets through gspread, or CSV files on disk.

A table is a list of rows, each a list of cell strings, exactly as a sheet holds it.
Parsers never touch this module; they take tables.
"""

import csv
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

Table = list[list[str]]

MAX_PARALLEL = 8  # requests in flight at once; Google starts refusing well above this
DEFAULT_TAB = "Sheet1"  # what Google calls the one tab a new spreadsheet comes with
FOLDER_MIME = "application/vnd.google-apps.folder"

_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def _looks_like_id(name: str) -> bool:
    """Whether a sheet name is a Drive id rather than a role nobody has chosen a sheet for."""
    return bool(_DRIVE_ID.match(name))


@dataclass(frozen=True)
class Fill:
    """A background colour on one cell: the 0-based row and column, and a hex colour."""

    row: int
    column: int
    colour: str


@dataclass(frozen=True)
class Styled:
    """A table plus the formatting Google Sheets should apply to it.

    Everything here is advice a sheet may ignore: a CSV file takes the rows and drops the
    rest, which is why the views build one object rather than formatting as they go.
    """

    rows: Table
    title_span: int = 0  # merge row 1 across this many columns
    bold_rows: tuple[int, ...] = ()  # 0-based row indexes
    freeze_rows: int = 0
    fills: tuple[Fill, ...] = field(default_factory=tuple)


class LoadError(Exception):
    """Bad or missing sheet data. The message names the sheet, tab, and cell or row."""


class NotACampDay(LoadError):
    """The date asked for is not on the Calendar sheet.

    It is a load error like any other, but its own kind, because it is the one the Puppet
    Master causes rather than the sheets: it means pick another date, not go and fix a tab.
    """


class Source(Protocol):
    """A collection of named spreadsheets, each a collection of named tabs."""

    def tabs(self, sheet: str) -> list[str]:
        """Tab names in a spreadsheet."""

    def read(self, sheet: str, tab: str) -> Table:
        """All cells of a tab. Missing tab raises LoadError."""

    def read_many(self, sheet: str, tabs: list[str]) -> dict[str, Table]:
        """Several tabs of one spreadsheet, in as few requests as possible."""

    def group(self, folder: str) -> dict[str, str]:
        """Every spreadsheet in a named folder: its title -> a name `read` accepts."""

    def read_group(self, folder: str, tab: str) -> dict[str, Table]:
        """One tab of every spreadsheet in a folder, by spreadsheet title."""

    def read_all(self, sheets: dict[str, str], tab: str) -> dict[str, Table]:
        """One tab of each of these spreadsheets, by the title each came under."""

    def documents(self, root: str, path: tuple[str, ...]) -> dict[str, str]:
        """Spreadsheets in `root/<path>`: title -> a name `read` accepts. Missing folder: {}."""

    def create(self, root: str, path: tuple[str, ...], title: str, tabs: list[str]) -> str:
        """Make a spreadsheet with these tabs at `root/<path>`, and the folders above it."""

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Replace a tab's contents, creating the tab if needed."""

    def style(self, sheet: str, tab: str, styled: Styled):
        """Apply a Styled's formatting. Where formatting is not possible, no-op."""


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

    def group(self, folder: str) -> dict[str, str]:
        """Sub-folders of `<root>/<folder>`, each a spreadsheet of CSV files."""
        base = self.root / folder
        if not base.is_dir():
            return {}
        return {p.name: f"{folder}/{p.name}" for p in sorted(base.iterdir()) if p.is_dir()}

    def read_group(self, folder: str, tab: str) -> dict[str, Table]:
        """That tab of each spreadsheet in the folder."""
        return {title: self.read(name, tab) for title, name in self.group(folder).items()}

    def read_all(self, sheets: dict[str, str], tab: str) -> dict[str, Table]:
        """That tab of each of these spreadsheets."""
        return {title: self.read(name, tab) for title, name in sheets.items()}

    def documents(self, root: str, path: tuple[str, ...]) -> dict[str, str]:
        """Sub-folders of `<root>/<path>`, each a spreadsheet of CSV files."""
        inside = "/".join((root, *path))
        return self.group(inside)

    def create(self, root: str, path: tuple[str, ...], title: str, tabs: list[str]) -> str:
        """Make the folders and an empty CSV file per tab."""
        name = "/".join((root, *path, title))
        for tab in tabs:
            path_of = self.root / name / f"{tab}.csv"
            if not path_of.exists():
                self.write(name, tab, [])
        (self.root / name).mkdir(parents=True, exist_ok=True)
        return name

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Write one CSV file."""
        path = self.root / sheet / f"{tab}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(table)

    def style(self, sheet: str, tab: str, styled: Styled):
        """CSV files carry no formatting."""


class SheetsSource:
    """Tables read from Google Sheets as whoever signed in.

    Every API call takes a noticeable fraction of a second, so tab lists are cached per
    spreadsheet and `read_many` fetches all the tabs it is asked for in one request.

    A sheet is named either by its role — `config`, `skills` — or by its Drive id, which
    is how a folder of sheets nobody named one at a time can still be read.
    """

    def __init__(
        self,
        sheet_ids: dict[str, str],
        credentials: object,
        folders: dict[str, str] | None = None,
    ) -> None:
        import gspread

        self.client = gspread.authorize(credentials)
        self.credentials = credentials
        self.sheet_ids = sheet_ids
        self.folder_ids = folders or {}
        self._open: dict[str, object] = {}
        self._tabs: dict[str, list[str]] = {}
        self._drive = None

    @property
    def drive(self):
        """Drive, opened on first use: most runs never browse or list a folder."""
        from puppet_strings.drive import Drive

        if self._drive is None:
            self._drive = Drive(self.credentials)
        return self._drive

    def _spreadsheet(self, sheet: str):
        key = self.sheet_ids.get(sheet, sheet)  # an unnamed sheet is named by its own id
        if key == sheet and sheet not in self.sheet_ids and not _looks_like_id(sheet):
            raise LoadError(f"{sheet}: no spreadsheet chosen; pick one in Configure")
        if sheet not in self._open:
            self._open[sheet] = self.client.open_by_key(key)
        return self._open[sheet]

    def group(self, folder: str) -> dict[str, str]:
        """Every spreadsheet in a chosen Drive folder, by title."""
        if folder not in self.folder_ids:
            raise LoadError(f"{folder}: no folder chosen; pick one in Configure")
        return {f.name: f.id for f in self.drive.spreadsheets(self.folder_ids[folder])}

    def read_group(self, folder: str, tab: str) -> dict[str, Table]:
        """One tab of every spreadsheet in a folder, fetched all at once.

        A season is a couple of dozen sheets and a request each would take the best part of
        a minute, so they go out together and wait in parallel.
        """
        return self.read_all(self.group(folder), tab)

    def read_all(self, sheets: dict[str, str], tab: str) -> dict[str, Table]:
        """That tab of each of these spreadsheets, in parallel, by the title they came under."""
        if not sheets:
            return {}
        with ThreadPoolExecutor(max_workers=min(len(sheets), MAX_PARALLEL)) as pool:
            tables = pool.map(lambda key: self.read(key, tab), sheets.values())
            return dict(zip(sheets, tables, strict=True))

    def documents(self, root: str, path: tuple[str, ...]) -> dict[str, str]:
        """Spreadsheets in `root/<path>`, by title. A folder that is not there holds nothing."""
        folder = self._walk(root, path, make=False)
        if folder is None:
            return {}
        return {f.name: f.id for f in self.drive.spreadsheets(folder)}

    def create(self, root: str, path: tuple[str, ...], title: str, tabs: list[str]) -> str:
        """Make a spreadsheet with these tabs at `root/<path>`, and the folders above it.

        A spreadsheet already there is left alone apart from the tabs it is missing, so this
        is safe to call on a day that has been published for a week.
        """
        folder = self._walk(root, path, make=True)
        sheet = self.drive.spreadsheet(folder, title)
        self._open[sheet.id] = self.client.open_by_key(sheet.id)
        self._tabs.pop(sheet.id, None)
        for tab in tabs:
            if tab not in self.tabs(sheet.id):
                self._spreadsheet(sheet.id).add_worksheet(tab, rows=100, cols=26)
                self._tabs.pop(sheet.id, None)
        self._drop_first_sheet(sheet.id, tabs)
        return sheet.id

    def _drop_first_sheet(self, key: str, tabs: list[str]) -> None:
        """Remove the empty `Sheet1` Google gives a new spreadsheet, once it has real tabs."""
        import gspread

        if not tabs:
            return
        try:
            spare = self._spreadsheet(key).worksheet(DEFAULT_TAB)
        except gspread.WorksheetNotFound:
            return
        self._spreadsheet(key).del_worksheet(spare)
        self._tabs.pop(key, None)

    def _walk(self, root: str, path: tuple[str, ...], make: bool) -> str | None:
        """The folder id at `root/<path>`, made on the way down when `make`."""
        if root not in self.folder_ids:
            raise LoadError(f"{root}: no folder chosen; pick one in Configure")
        here = self.folder_ids[root]
        for name in path:
            if make:
                here = self.drive.folder(here, name).id
                continue
            found = self.drive.child(here, name, FOLDER_MIME)
            if found is None:
                return None
            here = found.id
        return here

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

    def style(self, sheet: str, tab: str, styled: Styled):
        """Merge the title, bold the rows, freeze the top rows, fill the coloured cells.

        Every cell is cleared back to plain first, so republishing a shorter schedule does
        not leave yesterday's colours under it. The fills go in one `batch_format` call: a
        printed day is hundreds of coloured cells, and a request each would take longer
        than the solve did.
        """
        from gspread.utils import rowcol_to_a1

        worksheet = self._spreadsheet(sheet).worksheet(tab)
        worksheet.unmerge_cells(f"A1:{rowcol_to_a1(max(worksheet.row_count, 1), 26)}")
        worksheet.format("A1:Z1000", _PLAIN)
        if styled.title_span > 1:
            worksheet.merge_cells(f"A1:{rowcol_to_a1(1, styled.title_span)}")
        for row in styled.bold_rows:
            worksheet.format(f"A{row + 1}:Z{row + 1}", {"textFormat": {"bold": True}})
        worksheet.freeze(rows=styled.freeze_rows)
        batch = [
            {"range": _a1(fill), "format": {"backgroundColor": _rgb(fill.colour)}}
            for fill in styled.fills
        ]
        if batch:
            worksheet.batch_format(batch)


# What every cell is reset to before the day's own formatting goes on.
_PLAIN = {
    "textFormat": {"bold": False},
    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
}


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


def _a1(fill: Fill) -> str:
    """A fill's cell as a sheet writes it: row 0, column 0 is A1."""
    from gspread.utils import rowcol_to_a1

    return rowcol_to_a1(fill.row + 1, fill.column + 1)


def _rgb(colour: str) -> dict[str, float]:
    """`#rrggbb` as the red/green/blue fractions the Sheets API wants."""
    text = colour.lstrip("#")
    return {
        name: int(text[i : i + 2], 16) / 255 for name, i in (("red", 0), ("green", 2), ("blue", 4))
    }


def parse_int(value: str, where: str) -> int:
    """An integer cell, or a LoadError naming the cell."""
    try:
        return int(value)
    except ValueError as e:
        raise LoadError(f"{where}: expected a whole number, got '{value}'") from e


# How a time may be written. A leading zero is optional, and a spreadsheet's own 12-hour
# formatting is understood, so 8:30, 08:30 and 8:30 AM all mean the same thing.
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%I:%M:%S%p")


def parse_time(text: str, where: str) -> time:
    """A time cell, however the sheet happens to write it."""
    cleaned = " ".join(text.strip().upper().replace(".", "").split())
    for pattern in TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, pattern).time()
        except ValueError:
            continue
    raise LoadError(f"{where}: time '{text}' must look like 8:30, 08:30 or 8:30 AM")


# How a date may be written. A Google Sheets cell formatted as a date is read back as
# whatever it *displays*, which depends on the sheet's locale and the format chosen, so a
# column of real dates arrives as "6/14/2026", "14 Jun 2026" or "Sunday, June 14, 2026"
# rather than the ISO the sheet holds underneath.
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%a %b %d %Y",
    "%A %B %d %Y",
)

MONTH_FIRST = "mdy"  # 6/14/2026 is 14 June, as a sheet in the United States writes it
DAY_FIRST = "dmy"  # 14/6/2026 is 14 June, as most of the rest of the world writes it
DATE_ORDERS = (MONTH_FIRST, DAY_FIRST)

# A date cell may carry a time it does not need; "6/14/2026 0:00:00" is still a date.
_TIME_TAIL = re.compile(r"[ \t]+\d{1,2}:\d{2}(:\d{2})?([ \t]*[AaPp]\.?[Mm]\.?)?$")
_PUNCTUATION = re.compile(r"[,.]")
_NUMERIC = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})$")

# Google Sheets counts days from 1899-12-30, which is what an unformatted date cell holds.
SHEETS_EPOCH = date(1899, 12, 30)
MAX_SERIAL = 2958465  # 9999-12-31, past which a bare number is not a date


def parse_date(text: str, where: str, order: str = MONTH_FIRST) -> date:
    """A date cell, however the sheet happens to write it.

    `order` decides the one case nothing else can: a numeric date whose first two parts are
    both twelve or less, where 6/7/2026 is the sixth of July in one country and the seventh
    of June in another. Every other spelling says which it is and is read whatever `order`
    says.
    """
    cleaned = _TIME_TAIL.sub("", text.strip())
    if not cleaned:
        raise LoadError(f"{where}: no date")
    serial = _serial(cleaned)
    if serial is not None:
        return serial
    numeric = _numeric_date(cleaned, order, where)
    if numeric is not None:
        return numeric
    plain = " ".join(_PUNCTUATION.sub(" ", cleaned).split())
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(plain, pattern).date()
        except ValueError:
            continue
    raise LoadError(
        f"{where}: date '{text}' must be YYYY-MM-DD, or a date the sheet is formatting, "
        "such as 6/14/2026 or 14 June 2026"
    )


def _serial(text: str) -> date | None:
    """A Google Sheets date serial, which is what an unformatted date cell reads back as."""
    if not text.isdigit():
        return None
    number = int(text)
    if not 1 <= number <= MAX_SERIAL:
        return None
    return SHEETS_EPOCH + timedelta(days=number)


def _numeric_date(text: str, order: str, where: str) -> date | None:
    """A date written in numbers, or None if it is not written that way at all."""
    match = _NUMERIC.match(text)
    if not match:
        return None
    first, second, third = (int(part) for part in match.groups())
    if len(match.group(1)) == 4:  # 2026/06/14, which says what it is
        return _date(first, second, third, where, text)
    year = third if len(match.group(3)) == 4 else 2000 + third
    if first > 12:  # 14/6/2026 can only be day first
        return _date(year, second, first, where, text)
    if second > 12:  # 6/14/2026 can only be month first
        return _date(year, first, second, where, text)
    month, day = (first, second) if order == MONTH_FIRST else (second, first)
    return _date(year, month, day, where, text)


def _date(year: int, month: int, day: int, where: str, text: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as e:
        raise LoadError(f"{where}: date '{text}' is not a real date") from e


def split_list(value: str) -> list[str]:
    """A comma-separated cell as a list of stripped items."""
    return [item.strip() for item in value.split(",") if item.strip()]
