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
from time import sleep
from typing import Protocol

from puppet_strings.sheets.cache import TABS, SheetCache

Table = list[list[str]]

MAX_PARALLEL = 4  # requests in flight at once; Google starts refusing well above this

# Google's quotas are per minute per person: sixty write requests, three hundred reads. A
# day that spends them is told to come back later rather than refused outright, so it waits
# and asks again, for long enough that the minute the quota is counted over has turned over.
TOO_FAST = (429, 503)
WAITS = (5, 15, 30)
DEFAULT_TAB = "Sheet1"  # what Google calls the one tab a new spreadsheet comes with

# What a spreadsheet has to be called in the Puppet Strings folder to be recognised, so that
# choosing the root is the whole of the setup. Matched without regard to case.
SHEET_ROLES = {
    "clinic_data": "clinic_data",
    "clinic_schedule": "clinic_schedule",
    "skills": "skills",
    "config": "config",
}
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

    `column_widths` are (first column, last column, pixels), 0-based and the last column
    included, because a grid of names wants narrow columns and a grid of sentences wants
    wide ones, and Sheets' own guess is one width for everything.
    """

    rows: Table
    title_span: int = 0  # merge row 1 across this many columns
    bold_rows: tuple[int, ...] = ()  # 0-based row indexes
    freeze_rows: int = 0
    freeze_columns: int = 0
    wrap: bool = False  # let a long cell take two lines rather than running under its neighbour
    column_widths: tuple[tuple[int, int, int], ...] = ()
    fills: tuple[Fill, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """A frozen column may not cut a merged title in half, and Google says so.

        The freeze is a line down the sheet and a merged cell cannot straddle it; asking
        for both is a 400 from the API in the middle of publishing a day, which is the
        worst place to find out. A view wanting a frozen column writes its title in the
        first cell instead of merging it, where it overflows to the right and reads the
        same.
        """
        if 0 < self.freeze_columns < self.title_span:
            raise ValueError(
                f"a title merged across {self.title_span} columns cannot be split by a "
                f"freeze at column {self.freeze_columns}"
            )


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

    def subfolders(self, root: str, path: tuple[str, ...]) -> list[str]:
        """Names of the folders directly in `root/<path>`. Missing folder: []."""

    def discover(self, root: str, year: int) -> None:
        """Find the named spreadsheets under the root folder. Sources that need no lookup pass."""

    def refresh(self) -> None:
        """Ask again, from the next read on, what has changed. Sources that keep nothing pass."""

    def create(self, root: str, path: tuple[str, ...], title: str, tabs: list[str]) -> str:
        """Make a spreadsheet with these tabs at `root/<path>`, and the folders above it."""

    def name(self, role: str, key: str) -> None:
        """Let a role stand for a spreadsheet for the rest of the run, as `discover` does.

        It is what a spreadsheet just made is reached by: `create` returns the thing itself,
        and every reader asks for the role.
        """

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Replace a tab's contents, creating the tab if needed."""

    def write_many(self, sheet: str, tables: dict[str, Table]) -> None:
        """Replace several tabs of one spreadsheet, in as few requests as possible."""

    def style(self, sheet: str, tab: str, styled: Styled):
        """Apply a Styled's formatting. Where formatting is not possible, no-op."""


class CsvSource:
    """Tables stored as `<root>/<sheet>/<tab>.csv`."""

    def __init__(self, root: Path, names: dict[str, str] | None = None) -> None:
        self.root = Path(root)
        self.names = dict(names or {})  # a role -> the folder standing in for its spreadsheet

    def folder(self, sheet: str) -> Path:
        """Where a spreadsheet's tabs are, by role or by path."""
        return self.root / self.names.get(sheet, sheet)

    def name(self, role: str, key: str) -> None:
        """Point a role at a folder, as `discover` points one at a Drive id."""
        self.names[role] = key

    def tabs(self, sheet: str) -> list[str]:
        """Tab names, from the CSV file names."""
        folder = self.folder(sheet)
        if not folder.is_dir():
            raise LoadError(f"{sheet}: no folder {folder}")
        return sorted(p.stem for p in folder.glob("*.csv"))

    def read(self, sheet: str, tab: str) -> Table:
        """Rows of one CSV file."""
        path = self.folder(sheet) / f"{tab}.csv"
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
        return self.group("/".join((root, *path)))

    def subfolders(self, root: str, path: tuple[str, ...]) -> list[str]:
        """Folders on disk are spreadsheets, so a CSV tree has no folders of folders."""
        return sorted(self.group("/".join((root, *path))))

    def discover(self, root: str, year: int) -> None:
        """A CSV tree is addressed by folder name, so there is nothing to look up."""

    def refresh(self) -> None:
        """Every read of a CSV file is already fresh."""

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
        path = self.folder(sheet) / f"{tab}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(table)

    def write_many(self, sheet: str, tables: dict[str, Table]) -> None:
        """Each tab's rows. A file each is already as few requests as this takes."""
        for tab, table in tables.items():
            self.write(sheet, tab, table)

    def style(self, sheet: str, tab: str, styled: Styled):
        """CSV files carry no formatting."""


class SheetsSource:
    """Tables read from Google Sheets as whoever signed in.

    Every API call takes a noticeable fraction of a second, so tab lists are cached per
    spreadsheet and `read_many` fetches all the tabs it is asked for in one request.

    A sheet is named either by its role — `config`, `skills` — or by its Drive id, which
    is how a folder of sheets nobody named one at a time can still be read.

    With a `SheetCache`, a spreadsheet whose Drive version was seen in a folder listing
    since the last `refresh` is read off disk if it was read at that version before. One
    whose version is not known — named by an id in config.toml, in no folder that was
    listed — is always read from Google.
    """

    def __init__(
        self,
        sheet_ids: dict[str, str],
        credentials: object,
        folders: dict[str, str] | None = None,
        cache: SheetCache | None = None,
    ) -> None:
        import gspread

        self.client = gspread.authorize(credentials)
        self.credentials = credentials
        self.sheet_ids = sheet_ids
        self.folder_ids = folders or {}
        self.cache = cache
        self._versions: dict[str, str] = {}  # spreadsheet id -> its version when last listed
        self._open: dict[str, object] = {}
        self._tabs: dict[str, list[str]] = {}
        self._folders: dict[tuple[str, tuple[str, ...]], str] = {}  # where a path is in Drive
        self._discovered: set[tuple[str, int]] = set()
        self._drive = None

    def _sent(self, call):
        """Make one API call, waiting and going again if Google says it came too fast.

        Publishing a day and saving a request are a handful of requests each, which is well
        inside the quota; several of them in the same minute is not. Waiting is what the
        quota asks for, and the panel that is up while this runs says the window is busy.
        """
        for wait in (*WAITS, None):
            try:
                return call()
            except Exception as e:  # noqa: BLE001 - anything else is re-raised untouched
                if wait is None or not _too_fast(e):
                    raise
                sleep(wait)
        return None  # unreachable: the last turn of the loop either returns or raises

    @property
    def drive(self):
        """Drive, opened on first use: most runs never browse or list a folder."""
        from puppet_strings.drive import Drive

        if self._drive is None:
            self._drive = Drive(self.credentials)
        return self._drive

    def _key(self, sheet: str) -> str:
        key = self.sheet_ids.get(sheet, sheet)  # an unnamed sheet is named by its own id
        if key == sheet and sheet not in self.sheet_ids and not _looks_like_id(sheet):
            raise LoadError(f"{sheet}: no spreadsheet chosen; pick one in Configure")
        return key

    def _spreadsheet(self, sheet: str):
        """The spreadsheet, opened once. Opening it is a request for its metadata."""
        key = self._key(sheet)
        if sheet not in self._open:
            self._open[sheet] = self.client.open_by_key(key)
        return self._open[sheet]

    def group(self, folder: str) -> dict[str, str]:
        """Every spreadsheet in a chosen Drive folder, by title."""
        if folder not in self.folder_ids:
            raise LoadError(f"{folder}: no folder chosen; pick one in Configure")
        return self._listed(self.drive.spreadsheets(self.folder_ids[folder]))

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
        return self._listed(self.drive.spreadsheets(folder))

    def _listed(self, files) -> dict[str, str]:
        """Spreadsheets by title, remembering the version each was listed at."""
        for f in files:
            if f.version:
                self._versions[f.id] = f.version
        return {f.name: f.id for f in files}

    def refresh(self) -> None:
        """Forget which versions were seen, so the next load lists the folders again.

        Until then a spreadsheet is taken to be as it was when its folder was last listed,
        which is right for the length of one load and wrong for the length of a day.
        """
        self._versions = {}
        self._discovered = set()
        self._tabs = {}

    def _kept(self, key: str, tabs: list[str]) -> dict[str, list] | None:
        """These tabs off disk, if the spreadsheet has not changed since they were read."""
        version = self._versions.get(key)
        if self.cache is None or not version:
            return None
        return self.cache.get(key, version, tabs)

    def _keep(self, key: str, tables: dict[str, list]) -> None:
        version = self._versions.get(key)
        if self.cache is not None and version:
            self.cache.put(key, version, tables)

    def _forget(self, sheet: str) -> None:
        """A spreadsheet just written to: what was kept of it, and its version, are stale.

        `sheet` is the name it was written under, a role or an id; its tab list is
        remembered under that name, and everything else under the id.
        """
        key = self._key(sheet)
        self._versions.pop(key, None)
        self._tabs.pop(sheet, None)
        self._tabs.pop(key, None)
        if self.cache is not None:
            self.cache.drop(key)

    def subfolders(self, root: str, path: tuple[str, ...]) -> list[str]:
        """Names of the folders directly in `root/<path>`."""
        folder = self._walk(root, path, make=False)
        if folder is None:
            return []
        return sorted(f.name for f in self.drive.listing(folder) if f.folder)

    def discover(self, root: str, year: int) -> None:
        """Learn where the named spreadsheets are, by walking the root and reading names.

        The root holds a folder per year, and a sheet is looked for in the year being
        scheduled before the root, so a season can keep its own copy of one sheet without
        copying the rest.

        What is found wins over a spreadsheet id written in config.toml. A `[sheets]` table
        left over from before the folder was walked would otherwise pin every year to one
        season's sheets, which is the whole year folder defeated by a stale line. config.toml
        still supplies anything the walk does not find.
        """
        if root not in self.folder_ids:
            raise LoadError(f"{root}: no folder chosen; pick one in Configure")
        if (root, year) in self._discovered:
            return  # asked and answered: which spreadsheet is which is a thing of the tree
        found: dict[str, str] = {}
        for path in ((), (str(year),)):  # the year wins, so it is looked at second
            for title, key in self.documents(root, path).items():
                role = SHEET_ROLES.get(title.strip().lower())
                if role is not None:
                    found[role] = key
        self.sheet_ids = {**self.sheet_ids, **found}  # what is in the tree is the truth
        self._discovered.add((root, year))

    def name(self, role: str, key: str) -> None:
        """Point a role at a Drive id, as `discover` does from the names in the tree."""
        self.sheet_ids = {**self.sheet_ids, role: key}

    def create(self, root: str, path: tuple[str, ...], title: str, tabs: list[str]) -> str:
        """Make a spreadsheet with these tabs at `root/<path>`, and the folders above it.

        A spreadsheet already there is left alone apart from the tabs it is missing, so this
        is safe to call on a day that has been published for a week.

        The cache is kept up to date as the tabs are added rather than thrown away after
        each one: a day's spreadsheet is made with five tabs, and asking Google what tabs
        it has between every two of them is four requests spent learning what we just did.
        """
        folder = self._walk(root, path, make=True)
        sheet = self.drive.spreadsheet(folder, title)
        self._forget(sheet.id)
        self._open[sheet.id] = self.client.open_by_key(sheet.id)
        self._tabs.pop(sheet.id, None)
        have = list(self.tabs(sheet.id))
        for tab in tabs:
            if tab not in have:
                self._spreadsheet(sheet.id).add_worksheet(tab, rows=100, cols=26)
                have.append(tab)
        self._tabs[sheet.id] = have
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
        self._forget(key)

    def _walk(self, root: str, path: tuple[str, ...], make: bool) -> str | None:
        """The folder id at `root/<path>`, made on the way down when `make`.

        Every folder found is remembered for the rest of the run, prefixes included. A
        folder's id does not change while the window is open, and the tree is walked again
        for every span a load looks back over: `2027/Main Season/Session 3` is three Drive
        questions, of which the first two have the same answer as they did for session 2.

        What is *in* a folder is not remembered, only where the folder is, so a day added
        to the tree is still found by the next load.
        """
        if root not in self.folder_ids:
            raise LoadError(f"{root}: no folder chosen; pick one in Configure")
        here = self.folder_ids[root]
        for depth, name in enumerate(path):
            step = (root, path[: depth + 1])
            if step in self._folders:
                here = self._folders[step]
                continue
            if make:
                here = self.drive.folder(here, name).id
            else:
                found = self.drive.child(here, name, FOLDER_MIME)
                if found is None:
                    return None  # not remembered: it may be made before the next load
                here = found.id
            self._folders[step] = here
        return here

    def tabs(self, sheet: str) -> list[str]:
        """Worksheet titles, fetched once per spreadsheet.

        A spreadsheet not yet opened is asked for its metadata directly: opening it would
        fetch that same metadata, and listing its worksheets would then fetch it again.
        """
        if sheet not in self._tabs:
            key = self._key(sheet)
            kept = self._kept(key, [TABS])
            if kept is not None:
                titles = kept[TABS]
            elif sheet in self._open:
                titles = [ws.title for ws in self._open[sheet].worksheets()]
            else:
                metadata = self._sent(lambda: self.client.http_client.fetch_sheet_metadata(key))
                titles = [s["properties"]["title"] for s in metadata.get("sheets", [])]
            self._keep(key, {TABS: titles})
            self._tabs[sheet] = titles
        return self._tabs[sheet]

    def read(self, sheet: str, tab: str) -> Table:
        """All values of one worksheet."""
        return self.read_many(sheet, [tab])[tab]

    def read_many(self, sheet: str, tabs: list[str]) -> dict[str, Table]:
        """All values of several worksheets in one request.

        The values are asked for straight out, without asking first what tabs the
        spreadsheet has. That question is a request of its own, and a load reads a
        spreadsheet per published day and per cabin act sheet, so asking it every time
        doubles the number of requests a day costs. It is asked only when the read fails,
        which is the one time the answer says anything: it is what names the missing tab.
        """
        if not tabs:
            return {}
        key = self._key(sheet)
        kept = self._kept(key, tabs)
        if kept is not None:
            return kept
        ranges = [f"'{tab}'" for tab in tabs]
        batch_get = self._batch_get(sheet)
        try:
            response = self._sent(lambda: batch_get(ranges))
        except Exception as e:  # noqa: BLE001 - re-raised, once it can say what was wrong
            raise self._why_not(sheet, tabs, e) from e
        tables = {}
        for tab, value_range in zip(tabs, response.get("valueRanges", []), strict=True):
            tables[tab] = [list(row) for row in value_range.get("values", [])]
        self._keep(key, tables)
        return tables

    def _batch_get(self, sheet: str):
        """What reads values from a spreadsheet, without opening it just for that.

        Opening a spreadsheet fetches its metadata, which a read of values does not need,
        and a load reads a spreadsheet per published day: opening each would double the
        requests a load makes, and the quota of reads a minute it spends.
        """
        if sheet in self._open:
            return self._open[sheet].values_batch_get
        key = self._key(sheet)
        return lambda ranges: self.client.http_client.values_batch_get(key, ranges)

    def _why_not(self, sheet: str, tabs: list[str], failure: Exception) -> LoadError:
        """Why a read failed, in the words the Puppet Master can do something about."""
        try:
            missing = [tab for tab in tabs if tab not in self.tabs(sheet)]
        except Exception:  # noqa: BLE001 - the first failure is the one worth reporting
            missing = []
        if missing:
            return LoadError(f"{sheet}: no tab {', '.join(repr(t) for t in missing)}")
        return LoadError(f"{sheet}: could not be read ({failure})")

    def write(self, sheet: str, tab: str, table: Table) -> None:
        """Clear and refill a worksheet, adding it if missing."""
        self.write_many(sheet, {tab: table})

    def write_many(self, sheet: str, tables: dict[str, Table]) -> None:
        """Clear and refill several worksheets of one spreadsheet, in two requests.

        Google counts *write requests* against a quota of sixty a minute per person, and a
        published day is a spreadsheet of five tabs. A clear and a refill each would be ten
        of that minute's sixty before any formatting; a batch clear and a batch update are
        two, whatever the day holds.
        """
        if not tables:
            return
        spreadsheet = self._spreadsheet(sheet)
        self._add_missing(sheet, spreadsheet, tables)
        self._sent(lambda: spreadsheet.values_batch_clear(body={"ranges": _ranges(tables)}))
        data = [{"range": f"'{tab}'!A1", "values": table} for tab, table in tables.items() if table]
        if data:
            body = {"valueInputOption": "RAW", "data": data}
            self._sent(lambda: spreadsheet.values_batch_update(body))
        self._forget(sheet)

    def _add_missing(self, sheet: str, spreadsheet, tables: dict[str, Table]) -> None:
        """Make the tabs that are not there yet. A day made by `create` has them all."""
        have = set(self.tabs(sheet))
        for tab, table in tables.items():
            if tab in have:
                continue
            rows = max(len(table), 1)

            def add(tab: str = tab, rows: int = rows) -> None:
                spreadsheet.add_worksheet(tab, rows=rows, cols=26)

            self._sent(add)
            self._forget(sheet)

    def style(self, sheet: str, tab: str, styled: Styled):
        """Merge the title, bold the rows, freeze the corner, size the columns, fill the cells.

        Two requests, whatever the day holds: one for the shape of the sheet — what is
        merged, what is frozen, how wide the columns are — and one for how the cells are
        painted. Google allows sixty write requests a minute per person, and a bold row or
        a coloured cell each would spend a day's worth of them on one view.

        Every cell is cleared back to plain at the head of the painting, so republishing a
        shorter schedule does not leave yesterday's colours under it.
        """
        worksheet = self._spreadsheet(sheet).worksheet(tab)
        shape = self._shape(worksheet, styled)
        if shape:
            self._sent(lambda: worksheet.spreadsheet.batch_update({"requests": shape}))
        self._sent(lambda: worksheet.batch_format(self._paint(styled)))
        self._forget(sheet)  # formatting moves the version, and keeps no values

    @staticmethod
    def _shape(worksheet, styled: Styled) -> list[dict]:
        """What is merged, what is frozen, and how wide the columns are."""
        sheet_id = worksheet.id
        rows, columns = max(worksheet.row_count, 1), 26
        requests: list[dict] = [
            {
                "unmergeCells": {
                    "range": _grid(sheet_id, 0, rows, 0, columns)  # whatever was merged before
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "frozenRowCount": styled.freeze_rows,
                            "frozenColumnCount": styled.freeze_columns,
                        },
                    },
                    "fields": ("gridProperties.frozenRowCount,gridProperties.frozenColumnCount"),
                }
            },
        ]
        if styled.title_span > 1:
            merge = _grid(sheet_id, 0, 1, 0, styled.title_span)
            requests.append({"mergeCells": {"range": merge, "mergeType": "MERGE_ALL"}})
        requests += [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": first,
                        "endIndex": last + 1,
                    },
                    "properties": {"pixelSize": pixels},
                    "fields": "pixelSize",
                }
            }
            for first, last, pixels in styled.column_widths
        ]
        return requests

    @staticmethod
    def _paint(styled: Styled) -> list[dict]:
        """Every cell back to plain, then the bold rows, then the fills, in that order."""
        plain = _PLAIN | (_WRAPPED if styled.wrap else {})
        painting = [{"range": "A1:Z1000", "format": plain}]
        painting += [
            {"range": f"A{row + 1}:Z{row + 1}", "format": {"textFormat": {"bold": True}}}
            for row in styled.bold_rows
        ]
        painting += [
            {"range": _a1(fill), "format": {"backgroundColor": _rgb(fill.colour)}}
            for fill in styled.fills
        ]
        return painting


# What every cell is reset to before the day's own formatting goes on.
_PLAIN = {
    "textFormat": {"bold": False},
    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
}

# A cell that wraps and sits at the top of its row: two tasks in one block read as two
# lines rather than as one line running out under the next block's column.
_WRAPPED = {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}


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


def _too_fast(error: Exception) -> bool:
    """Whether Google is asking to be asked again rather than saying no."""
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) in TOO_FAST


def _ranges(tables: dict[str, Table]) -> list[str]:
    """A whole tab per name, as the values API wants them written."""
    return [f"'{tab}'" for tab in tables]


def _grid(sheet_id: int, top: int, bottom: int, left: int, right: int) -> dict:
    """A rectangle of one tab, in the half-open 0-based form the API takes."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": top,
        "endRowIndex": bottom,
        "startColumnIndex": left,
        "endColumnIndex": right,
    }


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
