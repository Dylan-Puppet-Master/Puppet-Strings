from datetime import date, time

from puppet_strings.config import Config
from puppet_strings.model import Assignment, Priority
from puppet_strings.publish.palette import BLOCK_COLOURS, CATEGORY_COLOURS, colour
from puppet_strings.publish.views import clinic_view, report, staff_view
from puppet_strings.publish.writer import is_published, publish
from puppet_strings.sheets.source import CsvSource
from puppet_strings.solver.result import RequestOutcome, Result


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
    table = staff_view(dataset, rows(dataset))
    assert table[0] == [
        "Staff",
        "Breakfast",
        "Clinic 1",
        "Clinic 2",
        "Lunch",
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
    custom = staff_view(dataset, rows(dataset), remainder="own work")
    assert {row[0]: row for row in custom[1:]}["James"][5] == "own work, then break"


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
    assert "Pole Course Explore Level 1 & 2 (DBL)" in labels  # offered, nobody assigned
    assert table[labels.index("Pole Course Explore Level 1 & 2 (DBL)")][1:] == ["", "", "", ""]
    assert "Muay Thai" not in labels  # not offered
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
    pole = labels.index("Pole Course Explore Level 1 & 2 (DBL)")
    assert not [c for c in range(1, 5) if (pole, c) in colours]  # offered, nobody on it


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
    source = CsvSource(tmp_path)
    result = Result(feasible=True, assignments=rows(dataset))
    publish(source, Config(), dataset, result)
    assert is_published(source, dataset)
    assert set(source.tabs("published")) == {"2026-09-16", "Staff View", "Clinic View", "Report"}
    tab = source.read("published", "2026-09-16")
    assert tab[0] == ["staff", "activity", "role", "block", "start", "minutes", "source"]
    assert ["Alexis", "Blacksmithing (DBL)", "first", "clinic_1", "09:15", "75", "offering"] in tab
    assert [
        "Dylan",
        "'counselor hour'",
        "",
        "clinic_2",
        "10:45",
        "60",
        "counselor-hours[dylan]",
    ] in tab
    assert source.read("published", "Staff View")[0][0] == "Staff"
    assert date.fromisoformat(source.tabs("published")[0])
