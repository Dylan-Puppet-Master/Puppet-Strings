"""SheetsSource against a fake gspread client: one batch request per spreadsheet."""

import pytest

from puppet_strings.drive import FOLDER_MIME, SHEET_MIME, DriveFile
from puppet_strings.sheets.source import (
    _PLAIN,
    CsvSource,
    Fill,
    LoadError,
    SheetsSource,
    Styled,
    _rgb,
)


class FakeWorksheet:
    def __init__(self, title):
        self.title = title


class FakeSpreadsheet:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def worksheets(self):
        self.calls.append("worksheets")
        return [FakeWorksheet(t) for t in self.tables]

    def values_batch_get(self, ranges):
        self.calls.append(("batch", tuple(ranges)))
        return {
            "valueRanges": [
                {
                    "range": r,
                    **({"values": self.tables[r.strip("'")]} if self.tables[r.strip("'")] else {}),
                }
                for r in ranges
            ]
        }


@pytest.fixture
def source(monkeypatch):
    spreadsheet = FakeSpreadsheet(
        {"Blocks": [["a", "b"], ["1"]], "Empty": [], "Calendar": [["date"]]}
    )
    src = SheetsSource.__new__(SheetsSource)
    src.sheet_ids = {"config": "id"}
    src._open = {"config": spreadsheet}
    src._tabs = {}
    src.folder_ids = {}
    return src, spreadsheet


def test_read_many_uses_one_batch_call_and_caches_tabs(source):
    src, spreadsheet = source
    tables = src.read_many("config", ["Blocks", "Empty", "Calendar"])
    assert tables == {"Blocks": [["a", "b"], ["1"]], "Empty": [], "Calendar": [["date"]]}
    assert spreadsheet.calls == ["worksheets", ("batch", ("'Blocks'", "'Empty'", "'Calendar'"))]
    assert src.read("config", "Blocks") == [["a", "b"], ["1"]]
    assert spreadsheet.calls.count("worksheets") == 1
    assert src.read_many("config", []) == {}


def test_missing_tab_is_a_load_error(source):
    src, _ = source
    with pytest.raises(LoadError, match="no tab 'Nope'"):
        src.read("config", "Nope")
    with pytest.raises(LoadError, match="no spreadsheet chosen"):
        src.read("published", "x")


class StyleWorksheet:
    """Enough of a gspread worksheet to record what `style` asks of it."""

    row_count = 10

    def __init__(self):
        self.formats = []
        self.batches = []
        self.merged = []
        self.frozen = None

    def unmerge_cells(self, a1):
        self.merged.clear()

    def merge_cells(self, a1):
        self.merged.append(a1)

    def format(self, a1, fmt):
        self.formats.append((a1, fmt))

    def freeze(self, rows):
        self.frozen = rows

    def batch_format(self, batch):
        self.batches.append(batch)


def test_style_sends_every_fill_in_one_batch(source):
    src, spreadsheet = source
    worksheet = StyleWorksheet()
    spreadsheet.worksheet = lambda tab: worksheet
    styled = Styled(
        rows=[["Clinic", "Clinic 1"]],
        title_span=2,
        bold_rows=(1,),
        freeze_rows=2,
        fills=(Fill(1, 0, "#cfe2ff"), Fill(1, 1, "#e8f0fe")),
    )
    src.style("config", "Clinic View", styled)
    assert worksheet.merged == ["A1:B1"] and worksheet.frozen == 2
    assert worksheet.formats[0] == ("A1:Z1000", _PLAIN)  # yesterday's colours cleared first
    assert worksheet.formats[1] == ("A2:Z2", {"textFormat": {"bold": True}})
    assert worksheet.batches == [
        [
            {
                "range": "A2",
                "format": {"backgroundColor": _rgb("#cfe2ff")},
            },
            {"range": "B2", "format": {"backgroundColor": _rgb("#e8f0fe")}},
        ]
    ]


def test_style_without_fills_asks_for_no_batch(source):
    src, spreadsheet = source
    worksheet = StyleWorksheet()
    spreadsheet.worksheet = lambda tab: worksheet
    src.style("config", "Clinic View", Styled(rows=[["a"]]))
    assert worksheet.batches == [] and worksheet.merged == []


def test_a_colour_becomes_the_fractions_the_api_wants():
    assert _rgb("#ffffff") == {"red": 1.0, "green": 1.0, "blue": 1.0}
    assert _rgb("#000000") == {"red": 0.0, "green": 0.0, "blue": 0.0}
    assert _rgb("#ff8000")["red"] == 1.0 and _rgb("#ff8000")["blue"] == 0.0


def test_csv_group_lists_each_spreadsheet_in_a_folder(fixtures_copy):
    src = CsvSource(fixtures_copy)
    assert src.group("cabin_acts") == {
        "Cabin Act Sorting - S1W1": "cabin_acts/Cabin Act Sorting - S1W1",
        "Cabin Act Sorting - S2W1": "cabin_acts/Cabin Act Sorting - S2W1",
    }
    assert src.group("nothing_here") == {}


def test_csv_read_group_reads_one_tab_of_each(fixtures_copy):
    boards = CsvSource(fixtures_copy).read_group("cabin_acts", "Board")
    assert set(boards) == {"Cabin Act Sorting - S1W1", "Cabin Act Sorting - S2W1"}
    assert boards["Cabin Act Sorting - S2W1"][0][0] == "Cabin Act Sorting - S2W1"


class FakeDrive:
    """A Drive of nested folders and spreadsheets, as name -> contents."""

    def __init__(self, tree):
        self.tree, self.ids, self.listed = tree, {}, []
        self._register("root", tree)

    def _register(self, key, node):
        self.ids[key] = node
        for name, child in node.items():
            if isinstance(child, dict):
                self._register(f"{key}/{name}", child)

    def listing(self, place):
        self.listed.append(place)
        node = self.ids.get(place, {})
        return [
            DriveFile(f"{place}/{name}", name, FOLDER_MIME if isinstance(c, dict) else SHEET_MIME)
            for name, c in node.items()
        ]

    def spreadsheets(self, folder_id):
        return [f for f in self.listing(folder_id) if not f.folder]

    def child(self, parent, name, mime):
        return next((f for f in self.listing(parent) if f.name == name and f.mime == mime), None)


def sheets_source(tree, **config):
    src = SheetsSource.__new__(SheetsSource)
    src.sheet_ids = config.get("sheet_ids", {})
    src.folder_ids = {"root": "root"}
    src._open, src._tabs = {}, {}
    src._drive = FakeDrive(tree)
    return src


TREE = {
    "Clinic_Schedule": "sheet",
    "Skills": "sheet",
    "2027": {
        "Clinic_Data": "sheet",
        "Skills": "sheet",
        "Config": "sheet",
        "Main Season": {"Session 1": {"Staff Categories": "sheet", "Monday_1": "sheet"}},
    },
}


def test_discover_finds_the_sheets_by_name():
    """Choosing the Puppet Strings folder is the whole of the setup."""
    src = sheets_source(TREE)
    src.discover("root", 2027)
    assert set(src.sheet_ids) == {"clinic_data", "clinic_schedule", "skills", "config"}
    assert src.sheet_ids["config"] == "root/2027/Config"
    assert src.sheet_ids["clinic_schedule"] == "root/Clinic_Schedule"  # only at the root


def test_the_year_wins_over_the_root():
    """A season may keep its own copy of one sheet without copying the rest."""
    src = sheets_source(TREE)
    src.discover("root", 2027)
    assert src.sheet_ids["skills"] == "root/2027/Skills"


def test_a_year_with_nothing_in_it_falls_back_to_the_root():
    src = sheets_source(TREE)
    src.discover("root", 2030)  # no such year folder
    assert src.sheet_ids["skills"] == "root/Skills"
    assert "config" not in src.sheet_ids  # Config lives only inside 2027


def test_what_is_found_wins_over_config_toml():
    """A stale [sheets] line would otherwise pin every year to one season's sheets."""
    src = sheets_source(TREE, sheet_ids={"skills": "stale"})
    src.discover("root", 2027)
    assert src.sheet_ids["skills"] == "root/2027/Skills"


def test_config_toml_fills_what_the_walk_cannot_find():
    src = sheets_source(TREE, sheet_ids={"clinic_data": "pinned"})
    src.discover("root", 2030)  # no such year, and Clinic_Data is only inside 2027
    assert src.sheet_ids["clinic_data"] == "pinned"


def test_discover_needs_a_root_folder():
    src = sheets_source(TREE)
    src.folder_ids = {}
    with pytest.raises(LoadError, match="no folder chosen"):
        src.discover("root", 2027)


def test_the_tree_is_walked_for_a_span_and_its_days():
    src = sheets_source(TREE)
    assert src.subfolders("root", ()) == ["2027"]
    assert src.subfolders("root", ("2027",)) == ["Main Season"]
    assert src.documents("root", ("2027", "Main Season", "Session 1")) == {
        "Staff Categories": "root/2027/Main Season/Session 1/Staff Categories",
        "Monday_1": "root/2027/Main Season/Session 1/Monday_1",
    }
    assert src.documents("root", ("2028",)) == {}  # a year that is not there holds nothing
