"""SheetsSource against a fake gspread client: one batch request per spreadsheet."""

import pytest

from puppet_strings.drive import FOLDER_MIME, SHEET_MIME, DriveFile
from puppet_strings.sheets.source import (
    _PLAIN,
    FRESH_SECONDS,
    CsvSource,
    Fill,
    LoadError,
    SheetsSource,
    Styled,
    _rgb,
)


class Clock:
    """A clock that stands still until a test moves it."""

    now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeWorksheet:
    def __init__(self, title):
        self.title = title


class FakeSpreadsheet:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []
        self.updates = []

    def batch_update(self, body):
        self.updates.append(body)

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
    src._open = {"id": spreadsheet}
    src._tabs = {}
    src._folders, src._discovered = {}, {}
    src.folder_ids = {}
    src.cache, src._versions, src._clock = None, {}, Clock()
    return src, spreadsheet


def test_read_many_asks_for_the_values_and_nothing_else(source):
    """A read is one request. What tabs a spreadsheet has is a question of its own, and a
    load reads a spreadsheet per published day, so asking it too would double the day."""
    src, spreadsheet = source
    tables = src.read_many("config", ["Blocks", "Empty", "Calendar"])
    assert tables == {"Blocks": [["a", "b"], ["1"]], "Empty": [], "Calendar": [["date"]]}
    assert spreadsheet.calls == [("batch", ("'Blocks'", "'Empty'", "'Calendar'"))]
    assert src.read("config", "Blocks") == [["a", "b"], ["1"]]
    assert "worksheets" not in spreadsheet.calls
    assert src.read_many("config", []) == {}
    assert spreadsheet.calls.count(("batch", ("'Blocks'",))) == 1  # and no request for nothing


def test_missing_tab_is_a_load_error(source):
    """The failed read is what asks what tabs there are, so the message still names it."""
    src, spreadsheet = source
    with pytest.raises(LoadError, match="no tab 'Nope'"):
        src.read("config", "Nope")
    assert "worksheets" in spreadsheet.calls  # asked once the read had failed, not before
    with pytest.raises(LoadError, match="no spreadsheet chosen"):
        src.read("published", "x")


class FakeHttpClient:
    """The raw API gspread sits on: what a spreadsheet not yet opened is read through."""

    def __init__(self, tables):
        self.spreadsheet = FakeSpreadsheet(tables)
        self.calls = []

    def values_batch_get(self, key, ranges):
        self.calls.append(("batch", key))
        return self.spreadsheet.values_batch_get(ranges)

    def fetch_sheet_metadata(self, key):
        self.calls.append(("metadata", key))
        return {"sheets": [{"properties": {"title": t}} for t in self.spreadsheet.tables]}


class FakeClient:
    def __init__(self, tables):
        self.http_client = FakeHttpClient(tables)

    def open_by_key(self, key):
        raise AssertionError("opening a spreadsheet fetches metadata a read does not need")


def test_a_spreadsheet_is_read_without_being_opened(source):
    """Opening one is a request for its metadata, and a load reads one per published day."""
    src, _ = source
    src.sheet_ids["skills"] = "skills-id"
    src.client = FakeClient({"Skills": [["name"]], "Positions": []})
    assert src.read("skills", "Skills") == [["name"]]
    assert src.tabs("skills") == ["Skills", "Positions"]
    assert src.tabs("skills") == ["Skills", "Positions"]  # asked once
    calls = src.client.http_client.calls
    assert calls == [("batch", "skills-id"), ("metadata", "skills-id")]


def test_a_role_that_moves_reads_the_spreadsheet_it_names_now(source):
    """config.toml names one Config and the tree another; what was opened as the first
    must not answer for the second once `discover` has moved the role over."""
    src, old = source
    assert src.tabs("config") == ["Blocks", "Empty", "Calendar"]
    src.read("config", "Blocks")
    src.client = FakeClient({"Blocks": [["new"]], "Mappings": [["m"]]})
    src.name("config", "tree-id")  # what discover does
    assert src.read_many("config", ["Blocks", "Mappings"]) == {
        "Blocks": [["new"]],
        "Mappings": [["m"]],
    }
    assert src.tabs("config") == ["Blocks", "Mappings"]
    assert ("batch", "tree-id") in src.client.http_client.calls


def test_a_read_that_fails_for_another_reason_says_what_happened(source):
    src, spreadsheet = source

    def refuse(ranges):
        raise RuntimeError("the network went away")

    spreadsheet.values_batch_get = refuse
    with pytest.raises(LoadError, match="the network went away"):
        src.read("config", "Blocks")


class WriteSpreadsheet(FakeSpreadsheet):
    """A spreadsheet that records the writes a publish sends it."""

    def __init__(self, tables, refusals=0):
        super().__init__(tables)
        self.cleared = []
        self.written = []
        self.added = []
        self.refusals = refusals

    def values_batch_clear(self, params=None, body=None):
        self.cleared.append(body["ranges"])

    def values_batch_update(self, body):
        if self.refusals:
            self.refusals -= 1
            raise _refused(429)
        self.written.append(body)

    def add_worksheet(self, title, rows, cols):
        self.added.append(title)
        self.tables[title] = []


def _refused(status):
    """What gspread raises when Google says a request came too fast."""
    error = RuntimeError(f"[{status}]: Quota exceeded")
    error.response = type("Response", (), {"status_code": status})()
    return error


def test_writing_several_tabs_takes_two_requests(source):
    """A published day is five tabs, and a clear and a refill each is ten of a minute's sixty."""
    src, _ = source
    spreadsheet = WriteSpreadsheet({"Blocks": [], "Empty": [], "Calendar": []})
    src._open["id"] = spreadsheet
    src.write_many("config", {"Blocks": [["a"]], "Calendar": [["b"], ["c"]], "Empty": []})
    assert spreadsheet.cleared == [["'Blocks'", "'Calendar'", "'Empty'"]]
    (body,) = spreadsheet.written
    assert body["valueInputOption"] == "RAW"
    assert body["data"] == [  # an empty tab is cleared and then has nothing to write
        {"range": "'Blocks'!A1", "values": [["a"]]},
        {"range": "'Calendar'!A1", "values": [["b"], ["c"]]},
    ]


def test_writing_a_tab_that_is_not_there_yet_makes_it(source):
    src, _ = source
    spreadsheet = WriteSpreadsheet({"Blocks": []})
    src._open["id"] = spreadsheet
    src._tabs["id"] = ["Blocks"]
    src.write_many("config", {"Report": [["x"]]})
    assert spreadsheet.added == ["Report"]
    assert spreadsheet.written[0]["data"] == [{"range": "'Report'!A1", "values": [["x"]]}]


def test_a_request_that_came_too_fast_waits_and_goes_again(source, monkeypatch):
    """Google's answer to a spent quota is to come back, so that is what is done."""
    slept = []
    monkeypatch.setattr("puppet_strings.sheets.source.sleep", slept.append)
    src, _ = source
    spreadsheet = WriteSpreadsheet({"Blocks": []}, refusals=2)
    src._open["id"] = spreadsheet
    src.write_many("config", {"Blocks": [["a"]]})
    assert slept == [5, 15]  # two refusals, two waits, and the third time it landed
    assert len(spreadsheet.written) == 1


def test_a_refusal_that_is_not_about_speed_is_raised(source, monkeypatch):
    monkeypatch.setattr("puppet_strings.sheets.source.sleep", lambda _: None)
    src, _ = source
    spreadsheet = WriteSpreadsheet({"Blocks": []})

    def forbidden(body):
        raise _refused(403)

    spreadsheet.values_batch_update = forbidden
    src._open["id"] = spreadsheet
    with pytest.raises(RuntimeError, match="403"):
        src.write_many("config", {"Blocks": [["a"]]})


def test_a_quota_that_never_frees_up_gives_up_saying_so(source, monkeypatch):
    monkeypatch.setattr("puppet_strings.sheets.source.sleep", lambda _: None)
    src, _ = source
    spreadsheet = WriteSpreadsheet({"Blocks": []}, refusals=99)
    src._open["id"] = spreadsheet
    with pytest.raises(RuntimeError, match="429"):
        src.write_many("config", {"Blocks": [["a"]]})


class StyleWorksheet:
    """Enough of a gspread worksheet to record what `style` asks of it."""

    row_count = 10
    id = 7

    def __init__(self, spreadsheet=None):
        self.batches = []
        self.spreadsheet = spreadsheet

    def batch_format(self, batch):
        self.batches.append(batch)


def styling(source, styled):
    """What one `style` call sends: the shape requests, then the painting."""
    src, spreadsheet = source
    worksheet = StyleWorksheet(spreadsheet)
    spreadsheet.worksheet = lambda tab: worksheet
    src.style("config", "A View", styled)
    shape = spreadsheet.updates[0]["requests"] if spreadsheet.updates else []
    return {r: body for request in shape for r, body in request.items()}, worksheet.batches


def test_style_shapes_the_sheet_in_one_request_and_paints_it_in_another(source):
    """Google counts sixty write requests a minute, and a day has two views to dress."""
    styled = Styled(
        rows=[["Clinic", "Clinic 1"]],
        title_span=2,
        bold_rows=(1,),
        freeze_rows=2,
        fills=(Fill(1, 0, "#cfe2ff"), Fill(1, 1, "#e8f0fe")),
    )
    shape, batches = styling(source, styled)
    assert len(source[1].updates) == 1 and len(batches) == 1  # two requests, whatever it holds
    assert shape["mergeCells"]["range"]["endColumnIndex"] == 2
    assert shape["unmergeCells"]["range"]["endRowIndex"] == 10  # whatever was merged before
    frozen = shape["updateSheetProperties"]["properties"]["gridProperties"]
    assert (frozen["frozenRowCount"], frozen["frozenColumnCount"]) == (2, 0)
    (painting,) = batches
    assert painting[0] == {"range": "A1:Z1000", "format": _PLAIN}  # yesterday's colours first
    assert painting[1] == {"range": "A2:Z2", "format": {"textFormat": {"bold": True}}}
    assert painting[2:] == [
        {"range": "A2", "format": {"backgroundColor": _rgb("#cfe2ff")}},
        {"range": "B2", "format": {"backgroundColor": _rgb("#e8f0fe")}},
    ]


def test_style_sizes_the_columns_and_wraps(source):
    """A view that says how wide its columns are says it in the request it is shaped by."""
    styled = Styled(
        rows=[["Staff", "Clinic 1"]],
        freeze_rows=2,
        freeze_columns=1,
        wrap=True,
        column_widths=((0, 0, 150), (1, 3, 190)),
    )
    shape, batches = styling(source, styled)
    assert "mergeCells" not in shape  # nothing merged, so nothing to cut the frozen column
    frozen = shape["updateSheetProperties"]["properties"]["gridProperties"]
    assert frozen["frozenColumnCount"] == 1
    widths = [
        r["updateDimensionProperties"]
        for r in source[1].updates[0]["requests"]
        if "updateDimensionProperties" in r
    ]
    assert [(w["range"]["startIndex"], w["range"]["endIndex"]) for w in widths] == [(0, 1), (1, 4)]
    assert [w["properties"]["pixelSize"] for w in widths] == [150, 190]
    assert batches[0][0]["format"]["wrapStrategy"] == "WRAP"


def test_a_view_with_nothing_to_paint_still_clears_what_was_there(source):
    _, batches = styling(source, Styled(rows=[["a"]]))
    assert batches == [[{"range": "A1:Z1000", "format": _PLAIN}]]


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
    src._folders, src._discovered = {}, {}
    src.cache, src._versions, src._clock = None, {}, Clock()
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


# -- the cache ---------------------------------------------------------------------------------


@pytest.fixture
def cached(source, tmp_path):
    """A source with a cache, whose config spreadsheet was listed at version 7."""
    from puppet_strings.sheets.cache import SheetCache

    src, spreadsheet = source
    src.cache = SheetCache(tmp_path / "cache.sqlite")
    src._listed([DriveFile("id", "Config", SHEET_MIME, "7")])
    return src, spreadsheet


def reads(spreadsheet) -> int:
    return sum(1 for call in spreadsheet.calls if call[0] == "batch")


def test_a_spreadsheet_that_has_not_changed_is_read_off_disk(cached):
    src, spreadsheet = cached
    assert src.read_many("config", ["Blocks", "Empty"])["Blocks"] == [["a", "b"], ["1"]]
    assert src.read_many("config", ["Blocks", "Empty"]) == {
        "Blocks": [["a", "b"], ["1"]],
        "Empty": [],
    }
    assert reads(spreadsheet) == 1
    src.read("config", "Calendar")  # a tab not read before is asked for
    assert reads(spreadsheet) == 2


def test_a_new_version_is_read_again(cached):
    src, spreadsheet = cached
    src.read("config", "Blocks")
    src._listed([DriveFile("id", "Config", SHEET_MIME, "8")])  # what the next listing said
    spreadsheet.tables["Blocks"] = [["changed"]]
    assert src.read("config", "Blocks") == [["changed"]]
    assert reads(spreadsheet) == 2


def test_a_listing_from_a_load_ago_is_not_trusted_until_it_is_listed_again(cached):
    src, spreadsheet = cached
    src.read("config", "Blocks")
    src._clock.now += FRESH_SECONDS  # the next load
    src.read("config", "Blocks")
    assert reads(spreadsheet) == 2
    src._listed([DriveFile("id", "Config", SHEET_MIME, "7")])
    src.read("config", "Blocks")
    assert reads(spreadsheet) == 2  # listed at the version it was read at


def test_a_write_drops_what_was_kept(cached):
    src, _ = cached
    spreadsheet = WriteSpreadsheet({"Blocks": [["old"]], "Empty": [], "Calendar": []})
    src._open["id"] = spreadsheet
    src.read("config", "Blocks")
    src.write("config", "Blocks", [["new"]])
    spreadsheet.tables["Blocks"] = [["new"]]
    assert src.read("config", "Blocks") == [["new"]]
    assert src.cache.get("id", "7", ["Blocks"]) is None  # not kept: its version is unknown


def test_tab_names_are_kept_by_version_too(cached):
    src, spreadsheet = cached
    assert src.tabs("config") == ["Blocks", "Empty", "Calendar"]
    src._tabs = {}  # another run of the app, the same version listed
    assert src.tabs("config") == ["Blocks", "Empty", "Calendar"]
    assert spreadsheet.calls.count("worksheets") == 1


def test_a_listing_reads_each_files_version():
    from puppet_strings.drive import _file

    assert _file({"id": "x", "name": "Skills", "version": 12}).version == "12"
    assert _file({"id": "x"}).version == ""
