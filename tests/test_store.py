from puppet_strings.app.store import unique_id


def test_an_id_is_the_next_free_number_on_its_tab():
    """Ids come from the tab, not the description, which may be empty and may change."""
    assert unique_id("S4 Special", set()) == "s4-1"
    assert unique_id("S4 Clinics", {"s4-1"}) == "s4-2"  # both of a span's tabs number as one
    assert unique_id("S4 Special", {"s4-1", "s4-2"}) == "s4-3"
    assert unique_id("S4 Special", {"s4-2"}) == "s4-1"  # a gap left by a deletion is reused
    assert unique_id("Season Requests", set()) == "season-1"
    assert unique_id("Season Requests", {"breaks", "s4-1"}) == "season-1"


from datetime import date  # noqa: E402

from puppet_strings.app.groups import clean, same_group  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.model import DEFAULT_GROUPS  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from tests.conftest import TARGET, saved_requests  # noqa: E402


def test_group_names_ignore_case_and_spacing():
    assert clean("  Ropes   rewrite ") == "Ropes rewrite"
    assert clean("Ropes, rewrite") == "Ropes rewrite"  # a comma would split the cell in two
    assert same_group("ropes rewrite", "Ropes  Rewrite")
    assert not same_group("Ropes", "Ropes rewrite")


def store(fixtures_copy):
    """A store on a writable copy of the fixtures, loaded for the target date."""
    loaded = RequestStore(CsvSource(fixtures_copy), Config())
    loaded.load(TARGET)
    return loaded


def test_groups_start_with_the_defaults_and_keep_an_empty_one(fixtures_copy):
    s = store(fixtures_copy)
    assert s.groups == list(DEFAULT_GROUPS)
    assert s.add_group("  Ropes   rewrite ") == "Ropes rewrite"
    assert s.groups == [*DEFAULT_GROUPS, "Ropes rewrite"]
    assert s.count("Ropes rewrite") == 0
    assert s.add_group("ROPES REWRITE") == ""  # the same group by another spelling
    assert s.add_group("  ") == ""
    assert s.groups == [*DEFAULT_GROUPS, "Ropes rewrite"]


def test_groups_made_of_requests_are_sorted_after_the_defaults(fixtures_copy):
    s = store(fixtures_copy)
    s.set_group(["breaks"], "Zebra")
    s.set_group(["counselor-hours"], "apple")
    assert s.groups == [*DEFAULT_GROUPS, "apple", "Zebra"]
    assert s.count("Zebra") == 1 and s.count("apple") == 1


def test_a_request_is_on_one_shelf_and_moving_it_takes_it_off_the_last(fixtures_copy):
    s = store(fixtures_copy)
    breaks = next(r for r in s.requests if r.id == "breaks")
    assert breaks.group == "Special daily requests"
    s.set_group(["breaks"], "Ropes rewrite")
    assert next(r for r in s.requests if r.id == "breaks").group == "Ropes rewrite"
    assert s.count("Special daily requests") == 2  # it left the shelf it was on
    s.set_group(["breaks"], "")  # dragged onto Ungrouped
    assert next(r for r in s.requests if r.id == "breaks").group == ""


def test_renaming_and_deleting_a_group_rewrite_the_sheet(fixtures_copy):
    s = store(fixtures_copy)
    s.set_group(["breaks", "counselor-hours"], "Ropes rewrite")
    assert s.rename_group("Ropes rewrite", "Ropes") == "Ropes"
    assert s.rename_group("Ropes", "Special daily requests") == ""  # a name already taken
    assert s.rename_group("Ropes", " ") == ""
    assert saved_requests(s.source.root, "Season Requests")["breaks"].group == "Ropes"
    s.delete_group("ropes")
    assert "Ropes" not in s.groups
    assert all(r.group != "Ropes" for r in s.requests)


def test_a_request_saved_with_groups_and_a_requester_round_trips(fixtures_copy):
    from dataclasses import replace

    s = store(fixtures_copy)
    original = next(r for r in s.requests if r.id == "breaks")
    s.save(replace(original, group="Special daily requests", requester="rob"), "breaks")
    again = RequestStore(s.source, s.config)
    again.load(TARGET)
    saved = next(r for r in again.requests if r.id == "breaks")
    assert saved.requester == "rob" and saved.group == "Special daily requests"
    assert again.facets["breaks"].valid
    assert again.facets["breaks"].covers(date(2026, 9, 16))
