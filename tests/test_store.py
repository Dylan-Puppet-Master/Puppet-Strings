from puppet_strings.app.store import unique_id


def test_unique_id_from_description():
    assert unique_id("Dylan's day off", set()) == "dylan-s-day-off"
    assert unique_id("Dylan's day off", {"dylan-s-day-off"}) == "dylan-s-day-off-2"
    assert (
        unique_id("Dylan's day off", {"dylan-s-day-off", "dylan-s-day-off-2"})
        == "dylan-s-day-off-3"
    )
    assert unique_id("", set()) == "request"
    assert unique_id("", {"request"}) == "request-2"
    assert len(unique_id("x" * 100, set())) == 40


from datetime import date  # noqa: E402

from puppet_strings.app.groups import clean, same_group  # noqa: E402
from puppet_strings.app.store import RequestStore  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.model import DEFAULT_GROUPS  # noqa: E402
from puppet_strings.sheets.source import CsvSource  # noqa: E402
from tests.conftest import FIXTURES, TARGET  # noqa: E402


def test_group_names_ignore_case_and_spacing():
    assert clean("  Ropes   rewrite ") == "Ropes rewrite"
    assert clean("Ropes, rewrite") == "Ropes rewrite"  # a comma would split the cell in two
    assert same_group("ropes rewrite", "Ropes  Rewrite")
    assert not same_group("Ropes", "Ropes rewrite")


def store(tmp_path):
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    loaded = RequestStore(CsvSource(copy), Config())
    loaded.load(TARGET)
    return loaded


def test_groups_start_with_the_defaults_and_keep_an_empty_one(tmp_path):
    s = store(tmp_path)
    assert s.groups == list(DEFAULT_GROUPS)
    assert s.add_group("  Ropes   rewrite ") == "Ropes rewrite"
    assert s.groups == [*DEFAULT_GROUPS, "Ropes rewrite"]
    assert s.count("Ropes rewrite") == 0
    assert s.add_group("ROPES REWRITE") == ""  # the same group by another spelling
    assert s.add_group("  ") == ""
    assert s.groups == [*DEFAULT_GROUPS, "Ropes rewrite"]


def test_groups_made_of_requests_are_sorted_after_the_defaults(tmp_path):
    s = store(tmp_path)
    s.set_group(["breaks"], "Zebra", member=True)
    s.set_group(["breaks"], "apple", member=True)
    assert s.groups == [*DEFAULT_GROUPS, "apple", "Zebra"]
    assert s.count("Zebra") == 1 and s.count("apple") == 1


def test_a_request_keeps_its_other_groups(tmp_path):
    s = store(tmp_path)
    s.set_group(["breaks"], "Ropes rewrite", member=True)
    breaks = next(r for r in s.requests if r.id == "breaks")
    assert breaks.groups == ("Special daily requests", "Ropes rewrite")
    s.set_group(["breaks"], "ropes rewrite", member=False)  # spelled differently, same group
    assert next(r for r in s.requests if r.id == "breaks").groups == ("Special daily requests",)


def test_renaming_and_deleting_a_group_rewrite_the_sheet(tmp_path):
    s = store(tmp_path)
    s.set_group(["breaks", "counselor-hours"], "Ropes rewrite", member=True)
    assert s.rename_group("Ropes rewrite", "Ropes") == "Ropes"
    assert s.rename_group("Ropes", "Special daily requests") == ""  # a name already taken
    assert s.rename_group("Ropes", " ") == ""
    written = s.source.read("config", "Requests")
    column = written[0].index("groups")
    row = next(r for r in written if r[0] == "breaks")
    assert row[column] == "Special daily requests, Ropes"
    s.delete_group("ropes")
    assert "Ropes" not in s.groups
    assert all("Ropes" not in r.groups for r in s.requests)


def test_a_request_saved_with_groups_and_a_requester_round_trips(tmp_path):
    from dataclasses import replace

    s = store(tmp_path)
    original = next(r for r in s.requests if r.id == "breaks")
    s.save(replace(original, groups=("Special daily requests",), requester="rob"), "breaks")
    again = RequestStore(s.source, s.config)
    again.load(TARGET)
    saved = next(r for r in again.requests if r.id == "breaks")
    assert saved.requester == "rob" and saved.groups == ("Special daily requests",)
    assert again.facets["breaks"].valid
    assert again.facets["breaks"].covers(date(2026, 9, 16))
