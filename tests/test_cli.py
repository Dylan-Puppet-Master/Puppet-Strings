from puppet_strings.cli import main
from tests.conftest import FIXTURES


def test_validate_and_names(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "validate"]) == 0
    assert "30 of 30 requests valid" in capsys.readouterr().out
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "names"]) == 0
    out = capsys.readouterr().out
    assert "staff.cam_vl  (Cam VL)" in out
    assert "activity.any_clinic  (category" in out
    assert "block.meals" in out


def test_solve_prints_views_and_report(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-09-16", "solve"]) == 0
    out = capsys.readouterr().out
    assert "Staff   Clinic 1" in out
    assert "Day 4, Session 1 - Wednesday" in out
    assert "Blacksmithing (DBL)                    Alexis    Alexis" in out
    assert "unsatisfied  offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1" in out


def test_solve_publishes_to_fixture_copy(tmp_path, capsys):
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    args = ["--fixtures", str(copy), "--date", "2026-09-16", "solve", "--publish"]
    assert main(args) == 0
    assert (copy / "published" / "2026-09-16.csv").exists()
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
    rows = copy.joinpath("config", "Requests.csv").read_text()
    assert "offering:2026-09-17:riflery:clinic_3" in rows and "generated" in rows
    assert main(["--fixtures", str(copy), "--date", "2026-09-17", "solve"]) == 0
    assert "no offerings loaded" not in capsys.readouterr().out


def test_missing_calendar_date_is_an_error(capsys):
    assert main(["--fixtures", str(FIXTURES), "--date", "2026-12-25", "validate"]) == 1
    assert "not a camp day" in capsys.readouterr().err
