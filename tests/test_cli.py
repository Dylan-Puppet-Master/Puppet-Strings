import re

from puppet_strings.cli import main
from tests.conftest import FIXTURES


def test_validate_and_names(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "validate"]) == 0
    assert "31 of 31 requests valid" in capsys.readouterr().out
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "names"]) == 0
    out = capsys.readouterr().out
    assert "staff.cam_vl  (Cam VL)" in out
    assert "activities.clinics.all  (category" in out
    assert "blocks.meals" in out


def test_solve_prints_views_and_report(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "solve"]) == 0
    out = capsys.readouterr().out
    assert "Staff" in out and "Breakfast" in out and "Clinic 1" in out
    assert "Day 4, Session 1 Week 1 - Wednesday" in out
    assert re.search(r"Blacksmithing \(DBL\)\s+(\w+)\s+\1\b", out)
    assert "unsatisfied  offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1" in out


def test_solve_publishes_to_fixture_copy(tmp_path, capsys):
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    args = ["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--publish"]
    assert main(args) == 0
    day = copy / "root" / "2026" / "Main Season" / "Session 1" / "Wednesday_1"
    assert (day / "Assignments.csv").exists() and (day / "Staff View.csv").exists()
    assert main(args) == 1
    assert "already published" in capsys.readouterr().err
    assert main(args + ["--force"]) == 0


def test_load_offerings_and_missing_warning(tmp_path, capsys):
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    assert main(["--fixtures", str(copy), "--date", "2026-09-17", "solve"]) == 0
    assert "no offerings loaded for 2026-09-17" in capsys.readouterr().out
    assert main(["--fixtures", str(copy), "--date", "2026-09-17", "load-offerings"]) == 0
    assert "loaded 24 offerings for 2026-09-17" in capsys.readouterr().out
    rows = copy.joinpath("requests", "S1 Clinics.csv").read_text()
    assert "offering:2026-09-17:riflery:clinic_3" in rows and "generated" in rows
    assert main(["--fixtures", str(copy), "--date", "2026-09-17", "solve"]) == 0
    assert "no offerings loaded" not in capsys.readouterr().out


def test_missing_calendar_date_is_an_error(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-12-25", "validate"]) == 1
    assert "not a camp day" in capsys.readouterr().err


def published_copy(tmp_path):
    """A copy of the fixtures with 2026-09-16 solved and published."""
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    assert main(["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--publish"]) == 0
    return copy


def test_same_day_needs_a_published_schedule(tmp_path, capsys):
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    args = ["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--same-day"]
    assert main(args) == 1
    assert "has no published schedule to change" in capsys.readouterr().err


def test_same_day_reports_what_moved(tmp_path, capsys):
    copy = published_copy(tmp_path)
    capsys.readouterr()
    adjustments = copy / "config" / "Adjustments.csv"
    adjustments.write_text("date,staff,resting,RAL_penalty,note\n2026-09-16,Alesa,all day,,sick\n")
    args = ["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--same-day"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "today: Alesa is resting all day today (sick)" in out
    changes = re.search(r"Staff\s+Block\s+Was\s+Now(.*)", out, re.S).group(1)
    assert "Alesa" in changes


def test_same_day_publishes_over_the_day_without_force(tmp_path, capsys):
    copy = published_copy(tmp_path)
    args = ["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--same-day", "--publish"]
    assert main(args) == 0
    day = copy / "root" / "2026" / "Main Season" / "Session 1" / "Wednesday_1"
    assert (day / "Changes.csv").exists()  # a re-solve says what moved, beside the views
    assert "published 2026-09-16" in capsys.readouterr().out
