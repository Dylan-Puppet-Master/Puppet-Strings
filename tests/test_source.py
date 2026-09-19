"""SheetsSource against a fake gspread client: one batch request per spreadsheet."""

import pytest

from puppet_strings.sheets.source import (
    _PLAIN,
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
    with pytest.raises(LoadError, match="no spreadsheet id"):
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
