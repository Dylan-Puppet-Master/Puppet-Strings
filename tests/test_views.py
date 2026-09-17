from datetime import date, time

from puppet_strings.config import Config
from puppet_strings.model import Assignment, Priority
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
    assert table[0] == ["Day 4, Session 1 - Wednesday"]
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
