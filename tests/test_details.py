"""What a name in the Namespaces pane opens."""

import os
from datetime import date

import pytest

from puppet_strings.app.details import details, is_mapping
from tests.build import BUDDY_DEFAULT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def rows(found, heading):
    return dict(next(s for s in found.sections if s.heading == heading).rows)


def test_a_staff_member_shows_their_skills_and_categories(dataset):
    found = details("staff.dylan", dataset)
    assert found.subtitle == "Dylan, RAL 5"
    assert rows(found, "Skills")["archery_1_2"] == "\u2713"
    assert "staff.counselor" in rows(found, "In these categories")
    assert "staff.director" not in rows(found, "In these categories")


def test_a_skill_keeps_the_word_the_sheet_wrote(dataset):
    """A tick shows as a tick; anything else keeps its own word, which says more."""
    found = details("staff.paul", dataset)
    assert rows(found, "Skills")["candle_making"] == "w/ shadow"
    assert rows(found, "Skills")["any"] == "\u2713"
    assert "riflery" not in rows(found, "Skills")  # nothing written, nothing shown


def test_a_staff_category_shows_its_members(dataset):
    found = details("staff.counselor", dataset)
    assert found.subtitle == "3 working today"
    assert set(rows(found, "Members")) == {"Dylan", "James", "Paul"}


def test_a_clinic_shows_what_each_position_asks_for_and_who_could_hold_it(dataset):
    found = details("activities.clinics.canoe_1_2", dataset)
    asks = rows(found, "It asks for")
    assert asks["first: canoe at RAL 5"] == "Alesa"
    assert asks["lifeguard: lifeguard at RAL 5"] == "Alesa, Vic"


def test_a_cabin_act_shows_the_day_being_scheduled_and_its_card(dataset):
    found = details("activities.cabin_acts.m2", dataset)
    assert found.subtitle == "M2 Fort Building on 2026-09-16"
    asks = rows(found, "It asks for")
    assert asks["first: Vic"] == "Vic"  # asked for by name, so nobody else will do
    assert asks["second: Low Ropes"] == "Lisa, Vic"  # asked for by skill
    assert asks["third: Village HERO"] == "Audrey, Mogee"  # asked for by category
    assert rows(found, "On the cabin act board")["Activity"] == "Fort Building"


def test_a_cabin_with_nothing_on_today_says_which_days_it_has(dataset):
    found = details("activities.cabin_acts.p4", dataset)
    assert found.subtitle == "nothing on 2026-09-16"
    assert rows(found, "It does have these days") == {"2026-09-18": "P4 Tea Party"}


def test_a_set_of_activities_lists_them(dataset):
    found = details("activities.cabin_acts", dataset)
    assert found.subtitle == "4 activities"
    assert rows(found, "It holds")["M1 Lake Day"] == "2026-09-14"


@pytest.mark.parametrize("name", ["dates.target", "dates.session_1", "roles.first"])
def test_dates_and_roles_open_nothing(dataset, name):
    assert details(name, dataset) is None


def test_a_mapping_opens_its_table_instead(dataset):
    assert is_mapping("mappings.preference")
    assert not is_mapping("staff.dylan")
    assert details("mappings.preference", dataset) is None


def test_the_mapping_table_is_edited_and_written_back(fixtures_copy):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QTableWidgetItem

    from puppet_strings.app.details_dialog import MappingDialog
    from puppet_strings.config import Config
    from puppet_strings.sheets.source import CsvSource

    QApplication.instance() or QApplication([])
    source = CsvSource(fixtures_copy)
    dialog = MappingDialog(source, Config(), "preference")
    assert dialog.header == ["key1", "key2", "value"]
    before = len(source.read("config", "mapping_preference"))
    last = len([r for r in dialog.rows() if any(r)])
    for column, text in enumerate(("Dylan", "Riflery", "5")):
        dialog.grid.setItem(last - 1, column, QTableWidgetItem(text))
    dialog.save()
    written = source.read("config", "mapping_preference")
    assert written[0] == ["key1", "key2", "value"]
    assert written[-1] == ["Dylan", "Riflery", "5"]
    assert len(written) == before + 1


def test_the_mapping_table_keeps_what_it_was_given(fixtures_copy):
    """Saving without editing rewrites the tab unchanged, blank rows dropped."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from puppet_strings.app.details_dialog import MappingDialog
    from puppet_strings.config import Config
    from puppet_strings.sheets.source import CsvSource

    QApplication.instance() or QApplication([])
    source = CsvSource(fixtures_copy)
    before = source.read("config", "mapping_preference")
    MappingDialog(source, Config(), "preference").save()
    assert source.read("config", "mapping_preference") == before


def test_the_target_date_is_what_a_cabin_act_is_shown_for(source):
    from puppet_strings.config import Config
    from puppet_strings.sheets.load import load_dataset

    friday = load_dataset(source, Config(), date(2026, 9, 18))
    found = details("activities.cabin_acts.p4", friday)
    assert found.subtitle == "P4 Tea Party on 2026-09-18"
    assert rows(found, "It asks for")["first: Sarah"] == "Sarah"


def test_the_mapping_default_is_editable(fixtures_copy):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from puppet_strings.app.details_dialog import MappingDialog
    from puppet_strings.config import Config
    from puppet_strings.sheets.mappings import parse_mapping_index
    from puppet_strings.sheets.source import CsvSource

    QApplication.instance() or QApplication([])
    source = CsvSource(fixtures_copy)
    dialog = MappingDialog(source, Config(), "preference")
    assert dialog.default.value() == 3  # what the Mappings tab says now
    assert (dialog.default.minimum(), dialog.default.maximum()) == (1, 5)  # its own scale
    dialog.default.setValue(4)
    dialog.save()
    written = parse_mapping_index(source.read("config", "Mappings"))
    assert [m.default for m in written] == [4.0, BUDDY_DEFAULT]


def test_a_named_mapping_default_is_a_phrase(fixtures_copy):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from puppet_strings.app.details_dialog import MappingDialog
    from puppet_strings.config import Config
    from puppet_strings.sheets.mappings import parse_mapping_index
    from puppet_strings.sheets.source import CsvSource

    QApplication.instance() or QApplication([])
    source = CsvSource(fixtures_copy)
    dialog = MappingDialog(source, Config(), "buddy")
    assert dialog.default.text() == BUDDY_DEFAULT
    heading = dialog.grid.horizontalHeaderItem(0).text()
    assert heading == "key1: staff.counselor"  # says what the column holds
    dialog.default.setText("ANY 1 staff.office")
    dialog.save()
    written = parse_mapping_index(source.read("config", "Mappings"))
    assert written[1].default == "ANY 1 staff.office"
    assert source.read("config", "mapping_buddy")[0] == ["key1", "value"]  # not the headings


def test_a_mapping_default_cannot_leave_its_scale(fixtures_copy):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from puppet_strings.app.details_dialog import MappingDialog
    from puppet_strings.config import Config
    from puppet_strings.sheets.source import CsvSource

    QApplication.instance() or QApplication([])
    dialog = MappingDialog(CsvSource(fixtures_copy), Config(), "preference")
    dialog.default.setValue(99)
    assert dialog.default.value() == 5
