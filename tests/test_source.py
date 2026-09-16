"""SheetsSource against a fake gspread client: one batch request per spreadsheet."""

import pytest

from puppet_strings.sheets.source import LoadError, SheetsSource


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
