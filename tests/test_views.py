from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Assignment, Priority
from puppet_strings.publish.views import clinic_view, report, staff_view
from puppet_strings.publish.writer import is_published, publish
from puppet_strings.sheets.source import CsvSource
from puppet_strings.solver.result import RequestOutcome, Result


def rows(dataset):
    d = dataset.target
    return (
        Assignment("rob", "gravity_zip_line", "first", d, "clinic_1", "offering"),
        Assignment("james", "gravity_zip_line", "second", d, "clinic_1", "offering"),
        Assignment("paul", "gravity_zip_line", "shadow", d, "clinic_1", "train"),
        Assignment("alexis", "blacksmithing_dbl", "first", d, "clinic_1", "offering"),
        Assignment("alexis", "blacksmithing_dbl", "first", d, "clinic_2", "offering"),
        Assignment("dylan", "counselor hour", None, d, "clinic_2", "counselor-hours[dylan]"),
        Assignment("sarah", "break", None, d, "pm_break", "breaks[sarah]"),
        Assignment("sarah", "'x'", None, d, "work_projects", "wp"),
        Assignment("sarah", "setup", None, d, "playstation", "setup"),
    )


def test_staff_view(dataset):
    table = staff_view(dataset, rows(dataset))
    header = table[0]
    assert header == [
        "Staff",
        "Clinic 1",
        "Clinic 2",
        "Lunch Break",
        "Break Then Work Projects",
        "Clinic 3",
        "Clinic 4",
        "Playstation",
        "Evening Break",
    ]
    by_name = {row[0]: row for row in table[1:]}
    assert by_name["Rob"][1] == "Gravity Zip Line (1st)"
    assert by_name["James"][1] == "Gravity Zip Line (2nd)"
    assert by_name["Paul"][1] == "Gravity Zip Line (shadow)"
    assert (
        by_name["Alexis"][1] == "Blacksmithing (DBL)"
        and by_name["Alexis"][2] == "Blacksmithing (DBL)"
    )
    assert by_name["Dylan"][2] == "counselor hour"
    assert by_name["Sarah"][4] == "break; 'x'"
    assert by_name["Sarah"][7] == "setup" and by_name["Dylan"][7] == "Available"
    assert len(table) == 18


def test_clinic_view(dataset):
    table = clinic_view(dataset, rows(dataset))
    assert table[0] == ["Clinic", "Clinic 1", "Clinic 2", "Clinic 3", "Clinic 4"]
    by_name = {row[0]: row for row in table[1:]}
    assert by_name["Gravity Zip Line"][1] == "Rob\nJames\nPaul (shadow)"
    assert by_name["Blacksmithing (DBL)"][1:3] == ["Alexis", "Alexis"]
    assert "counselor hour" not in by_name


def test_report():
    result = Result(
        feasible=True,
        unsatisfied=(
            RequestOutcome("offering:salsa:clinic_4", Priority.CLINIC, "Salsa in clinic_4"),
        ),
        deferred=(RequestOutcome("maintenance", Priority.LOW, "archery maintenance"),),
        notes=("tier LOW hit the time limit; its score may not be optimal",),
    )
    assert report(result) == [
        ["status", "request", "priority", "description"],
        ["unsatisfied", "offering:salsa:clinic_4", "CLINIC", "Salsa in clinic_4"],
        ["deferred", "maintenance", "LOW", "archery maintenance"],
        ["note", "", "", "tier LOW hit the time limit; its score may not be optimal"],
    ]
    assert report(Result(feasible=False, conflicts=("a", "b")))[1:] == [
        ["conflict", "a", "MUST_HAPPEN", "infeasible together"],
        ["conflict", "b", "MUST_HAPPEN", "infeasible together"],
    ]


def test_publish_round_trip(dataset, tmp_path):
    source = CsvSource(tmp_path)
    result = Result(feasible=True, assignments=rows(dataset))
    assert not is_published(source, dataset) if (tmp_path / "published").exists() else True
    publish(source, Config(), dataset, result)
    assert is_published(source, dataset)
    assert set(source.tabs("published")) == {"2026-09-16", "Staff View", "Clinic View", "Report"}
    assert source.read("published", "2026-09-16")[0] == [
        "staff",
        "activity",
        "role",
        "block",
        "source",
    ]
    assert ["Alexis", "Blacksmithing (DBL)", "first", "clinic_1", "offering"] in source.read(
        "published", "2026-09-16"
    )
    assert ["Dylan", "'counselor hour'", "", "clinic_2", "counselor-hours[dylan]"] in source.read(
        "published", "2026-09-16"
    )
    assert source.read("published", "Staff View")[0][0] == "Staff"
    assert date.fromisoformat(source.tabs("published")[0])
