from datetime import time

from puppet_strings.model import Assignment, Priority
from puppet_strings.publish.palette import (
    BANDING,
    BLOCK_COLOURS,
    CATEGORY_COLOURS,
    NAME_COLUMN,
    colour,
)
from puppet_strings.publish.views import clinic_view, report, staff_view
from puppet_strings.publish.writer import day_sheet, is_published, publish
from puppet_strings.sheets.source import CsvSource
from puppet_strings.solver.result import RequestOutcome, Result
from tests.conftest import CONFIG


def rows(dataset):
    d = dataset.target

    def whole(staff, activity, role, block, source="offering"):
        b = dataset.blocks[block]
        return Assignment(staff, activity, role, d, block, b.start, b.minutes, source)

    def part(staff, activity, block, start, minutes, source):
        return Assignment(
            staff, activity, None, d, block, time.fromisoformat(start), minutes, source
        )

    return (
        # one clinic per category, since a clinic nobody is on has no row at all
        whole("vic", "archery_1_2", "first", "clinic_2"),
        whole("lucy", "riflery", "first", "clinic_3"),
        whole("tom", "canoe_1_2", "first", "clinic_4"),
        whole("jack", "candle_making", "first", "clinic_3"),
        whole("rob", "gravity_zip_line", "first", "clinic_1"),
        whole("james", "gravity_zip_line", "second", "clinic_1"),
        whole("paul", "gravity_zip_line", "shadow", "clinic_1", "train"),
        whole("alexis", "blacksmithing_dbl", "first", "clinic_1"),
        whole("alexis", "blacksmithing_dbl", "first", "clinic_2"),
        part("dylan", "counselor hour", "clinic_2", "10:45", 60, "counselor-hours[dylan]"),
        part("sarah", "break", "clinic_1", "09:15", 30, "breaks[sarah]"),
        part("sarah", "prep", "clinic_1", "10:00", 30, "prep"),
        part("james", "break", "clinic_3", "14:45", 30, "breaks[james]"),
        whole("sarah", "setup", None, "playstation", "setup"),
    )


def test_staff_view(dataset):
    view = staff_view(dataset, rows(dataset))
    table = view.rows[1:]  # row 0 is the title
    assert view.rows[0] == ["Day 4, Session 1 Week 1 - Wednesday"]
    assert table[0] == [
        "Staff",
        "Breakfast",
        "Clinic 1",
        "Clinic 2",
        "Lunch",
        "Cabin Act",
        "Clinic 3",
        "Clinic 4",
        "Playstation",
        "Evening",
        "Night",
    ]
    by_name = {row[0]: dict(zip(table[0], row, strict=True)) for row in table[1:]}
    assert by_name["Rob"]["Clinic 1"] == "Gravity Zip Line (1st)"
    assert by_name["James"]["Clinic 1"] == "Gravity Zip Line (2nd)"
    assert by_name["Paul"]["Clinic 1"] == "Gravity Zip Line (shadow)"
    assert (
        by_name["Alexis"]["Clinic 1"] == "Blacksmithing (DBL)"
        and by_name["Alexis"]["Clinic 2"] == "Blacksmithing (DBL)"
    )
    assert by_name["Dylan"]["Clinic 2"] == "counselor hour, then DYOW/WPs"
    assert by_name["Sarah"]["Clinic 1"] == "break, then DYOW/WPs, then prep"
    assert by_name["James"]["Clinic 3"] == "DYOW/WPs, then break"
    assert (
        by_name["Sarah"]["Playstation"] == "setup"
        and by_name["Dylan"]["Playstation"] == "Available"
    )
    assert len(table) == 22
    custom = staff_view(dataset, rows(dataset), remainder="own work").rows[1:]
    assert {row[0]: row for row in custom[1:]}["James"][6] == "own work, then break"


def test_the_staff_view_is_dressed_for_being_read(dataset):
    """It is the sheet everybody at camp opens, most of them looking for one row of it."""
    view = staff_view(dataset, rows(dataset))
    assert view.bold_rows == (0, 1)
    assert (view.freeze_rows, view.freeze_columns) == (2, 1) and view.wrap
    # the title is not merged: Google refuses a frozen column that cuts a merged cell
    assert view.title_span == 0
    assert [width for _, _, width in view.column_widths] == [150, 190]
    headings = {f.column: f.colour for f in view.fills if f.row == 1}
    assert headings[1] == colour(BLOCK_COLOURS, 0)  # the clinic view's colour for that block
    assert headings[0] == NAME_COLUMN
    names = {f.row for f in view.fills if f.column == 0}
    assert names == set(range(1, len(view.rows)))  # every name sits in the name column's shade
    banded = {f.row for f in view.fills if f.column == 1 and f.colour == BANDING}
    assert banded == set(range(3, len(view.rows), 2))  # every other row, below the headings


def test_a_frozen_column_may_not_cut_a_merged_title(dataset):
    """Publishing is the worst place to learn this, so it is refused where it is written."""
    import pytest

    from puppet_strings.sheets.source import Styled

    with pytest.raises(ValueError, match="cannot be split by a freeze"):
        Styled(rows=[["a", "b"]], title_span=2, freeze_columns=1)
    Styled(rows=[["a", "b"]], title_span=2, freeze_columns=2)  # the whole title is frozen
    Styled(rows=[["a", "b"]], title_span=2)  # or the column is not


def test_the_views_leave_out_whoever_is_not_at_camp(dataset):
    """A Skills row the span's Staff Categories sheet does not name is nobody's to read."""
    from dataclasses import replace

    away = replace(dataset, away=frozenset({"rob", "paul"}))
    names = [row[0] for row in staff_view(away, rows(dataset)).rows[2:]]
    assert "Rob" not in names and "Paul" not in names and "Dylan" in names
    free = [cell for row in clinic_view(away, ()).rows for cell in row]
    assert "Rob" not in free and "Dylan" in free


def excluded(dataset):
    """The fixture day with Dylan offsite all day and Sarah out for clinic 1."""
    from dataclasses import replace

    return replace(
        dataset,
        excluded={
            dataset.target: {
                "dylan": {b.id: "offsite" for b in dataset.blocks_on(dataset.target)},
                "sarah": {"clinic_1": "at the dentist"},
            }
        },
    )


def test_the_staff_view_says_where_somebody_excluded_is(dataset):
    view = staff_view(excluded(dataset), ())
    by_name = {row[0]: dict(zip(view.rows[1], row, strict=True)) for row in view.rows[2:]}
    assert set(by_name["Dylan"].values()) == {"Dylan", "offsite"}
    assert by_name["Sarah"]["Clinic 1"] == "at the dentist"
    assert by_name["Sarah"]["Clinic 2"] == ""  # back afterwards, and free
    assert by_name["Dylan"]["Playstation"] == "offsite"  # rather than Available


def test_the_clinic_view_groups_the_people_who_are_away(dataset):
    """They are neither on a clinic nor free, so they are their own row and not in DYOW/WPs."""
    view = clinic_view(excluded(dataset), ())
    labels = [row[0] if row else "" for row in view.rows]
    offsite = view.rows[labels.index("offsite")]
    assert offsite == ["offsite", "Dylan", "Dylan", "Dylan", "Dylan"]
    dentist = view.rows[labels.index("at the dentist")]
    assert dentist == ["at the dentist", "Sarah", "", "", ""]
    free = labels.index("DYOW/WPs")
    columns = {1: [], 2: []}
    for row in view.rows[free:]:
        for column in columns:
            if column < len(row) and row[column]:
                columns[column].append(row[column])
    assert "Dylan" not in columns[1] and "Dylan" not in columns[2]
    assert "Sarah" not in columns[1] and "Sarah" in columns[2]
    assert set(view.bold_rows) >= {labels.index("offsite"), labels.index("at the dentist")}


def test_clinic_view(dataset):
    view = clinic_view(dataset, rows(dataset))
    table = view.rows
    assert table[0] == ["Day 4, Session 1 Week 1 - Wednesday"]
    assert table[1] == ["Clinic", "Clinic 1", "Clinic 2", "Clinic 3", "Clinic 4"]
    assert view.title_span == 5 and view.freeze_rows == 2
    labels = [row[0] if row else "" for row in table]
    zip_line = labels.index("Gravity Zip Line")
    assert table[zip_line] == ["Gravity Zip Line", "Rob", "", "", ""]
    assert table[zip_line + 1] == ["", "James", "", "", ""]  # 2nd below 1st
    assert table[zip_line + 2] == ["Shadow", "Paul", "", "", ""]
    smith = labels.index("Blacksmithing (DBL)")
    assert table[smith] == ["Blacksmithing (DBL)", "Alexis", "Alexis", "", ""]
    # offered and nobody on it: deferred, or nobody could staff it, so it is not happening
    assert "Pole Course Explore Level 1 & 2 (DBL)" not in labels
    assert "Muay Thai" not in labels  # not offered either
    assert [] in table  # blank rows between categories
    hour = labels.index("counselor hour")
    assert table[hour] == ["counselor hour", "", "Dylan", "", ""]
    breaks = labels.index("break")
    assert table[breaks] == ["break", "Sarah", "", "James", ""]
    free = labels.index("DYOW/WPs")
    assert "Rob" not in [r[1] for r in table[free:]] and "Vic" in [r[1] for r in table[free:]]
    assert set(view.bold_rows) >= {0, 1, zip_line, smith, hour, breaks, free}
    assert labels.index("Archery 1 & 2") < zip_line < labels.index("Canoe 1 & 2")


def test_clinic_view_colours_each_block_column(dataset):
    view = clinic_view(dataset, rows(dataset))
    colours = {(f.row, f.column): f.colour for f in view.fills}
    assert len(colours) == len(view.fills)  # one fill per cell, never two
    headings = [colours[(1, c)] for c in range(1, 5)]
    assert headings == list(BLOCK_COLOURS[:4])  # the heading row is the legend
    labels = [row[0] if row else "" for row in view.rows]
    smith = labels.index("Blacksmithing (DBL)")
    assert view.rows[smith][1:] == ["Alexis", "Alexis", "", ""]
    assert colours[(smith, 1)] == BLOCK_COLOURS[0]  # a name takes its column's colour
    assert colours[(smith, 2)] == BLOCK_COLOURS[1]
    assert (smith, 3) not in colours  # and an empty cell stays white
    assert "Pole Course Explore Level 1 & 2 (DBL)" not in labels  # nobody on it, so no row


def test_clinic_view_colours_each_category(dataset):
    view = clinic_view(dataset, rows(dataset))
    colours = {(f.row, f.column): f.colour for f in view.fills}
    labels = [row[0] if row else "" for row in view.rows]
    weapons = [labels.index("Archery 1 & 2"), labels.index("Riflery")]
    arts = [labels.index("Candle Making"), labels.index("Blacksmithing (DBL)")]
    assert {colours[(r, 0)] for r in weapons} == {CATEGORY_COLOURS[0]}
    assert {colours[(r, 0)] for r in arts} == {CATEGORY_COLOURS[1]}
    zip_line = labels.index("Gravity Zip Line")
    shadow = labels.index("Shadow")
    assert colours[(shadow, 0)] == colours[(zip_line, 0)]  # a trainee row is in the group
    assert (labels.index("DYOW/WPs"), 0) not in colours  # and nothing else is


def test_colour_wraps_round_when_a_palette_runs_out():
    assert colour(BLOCK_COLOURS, len(BLOCK_COLOURS)) == BLOCK_COLOURS[0]
    assert colour(CATEGORY_COLOURS, len(CATEGORY_COLOURS) + 1) == CATEGORY_COLOURS[1]


def test_report():
    result = Result(
        feasible=True,
        unsatisfied=(
            RequestOutcome("offering:salsa:clinic_4", Priority.CLINIC, "Salsa in clinic_4"),
        ),
        deferred=(RequestOutcome("maintenance", Priority.LOW, "archery maintenance"),),
        inactive=(RequestOutcome("old", Priority.HIGH, "last week"),),
        notes=("tier LOW hit the time limit; its score may not be optimal",),
    )
    assert report(result) == [
        ["status", "request", "priority", "description"],
        ["unsatisfied", "offering:salsa:clinic_4", "CLINIC", "Salsa in clinic_4"],
        ["deferred", "maintenance", "LOW", "archery maintenance"],
        ["inactive", "old", "HIGH", "last week"],
        ["note", "", "", "tier LOW hit the time limit; its score may not be optimal"],
    ]
    assert report(Result(feasible=False, conflicts=("a", "b")))[1:] == [
        ["conflict", "a", "MUST_HAPPEN", "infeasible together"],
        ["conflict", "b", "MUST_HAPPEN", "infeasible together"],
    ]


def test_report_collapses_the_copies_of_one_request():
    """A clinic nobody can staff fails every position at once: one row, not one each."""
    clinic = "offering:2026-09-16:pole_course:clinic_1"
    result = Result(
        feasible=True,
        unsatisfied=tuple(
            RequestOutcome(f"{clinic}[{role}]", Priority.CLINIC, "Pole Course in clinic_1")
            for role in ("first", "second", "third")
        )
        + (RequestOutcome("breaks", Priority.MEDIUM, "a break each"),),
    )
    assert report(result)[1:] == [
        ["unsatisfied", clinic, "CLINIC", "Pole Course in clinic_1 (first; second; third)"],
        ["unsatisfied", "breaks", "MEDIUM", "a break each"],
    ]


def test_report_says_which_copies_failed_when_only_some_did():
    """Collapsing must not hide which Friday went wrong, so the keys follow the description."""
    result = Result(
        feasible=True,
        unsatisfied=(RequestOutcome("fridays[2026-09-18]", Priority.HIGH, "no break at lunch"),),
        deferred=(RequestOutcome("weekly[2026-09-18, clinic_1]", Priority.LOW, "tidy up"),),
    )
    assert report(result)[1:] == [
        ["unsatisfied", "fridays", "HIGH", "no break at lunch (2026-09-18)"],
        ["deferred", "weekly", "LOW", "tidy up (2026-09-18, clinic_1)"],
    ]


def test_report_leaves_an_id_that_only_looks_like_a_copy_alone():
    result = Result(
        feasible=True,
        unsatisfied=(RequestOutcome("odd[name", Priority.LOW, "kept whole"),),
        conflicts=("pin[dylan]", "pin[james]", "plain"),
    )
    assert report(result)[1:] == [
        ["unsatisfied", "odd[name", "LOW", "kept whole"],
        ["conflict", "pin", "MUST_HAPPEN", "infeasible together (dylan; james)"],
        ["conflict", "plain", "MUST_HAPPEN", "infeasible together"],
    ]


def test_publish_round_trip(dataset, tmp_path):
    """A solved day is written into its own spreadsheet in the schedules tree."""
    source = CsvSource(tmp_path)
    result = Result(feasible=True, assignments=rows(dataset))
    assert not is_published(source, CONFIG, dataset)
    publish(source, CONFIG, dataset, result)
    assert is_published(source, CONFIG, dataset)
    where = "root/2026/Main Season/Session 1/Wednesday_1"
    assert set(source.tabs(where)) == {
        "Offerings",  # publishing a day nobody made yet makes it, grid and all
        "Assignments",
        "Staff View",
        "Clinic View",
        "Report",
    }
    tab = source.read(where, "Assignments")
    assert tab[0] == ["staff", "activity", "role", "block", "start", "minutes", "source"]
    assert ["Alexis", "Blacksmithing (DBL)", "first", "clinic_1", "09:15", "75", "offering"] in tab


def test_a_day_sheet_is_made_with_its_tabs(dataset, tmp_path):
    """Load offerings makes the day a spreadsheet to fill in, before anything is solved."""
    source = CsvSource(tmp_path)
    day_sheet(source, CONFIG, dataset.this_span, dataset.target)
    where = "root/2026/Main Season/Session 1/Wednesday_1"
    assert set(source.tabs(where)) == {
        "Offerings",
        "Assignments",
        "Staff View",
        "Clinic View",
        "Report",
    }
    assert source.read(where, "Offerings") == []  # a grid to fill in
    assert not is_published(source, CONFIG, dataset)  # made is not solved
