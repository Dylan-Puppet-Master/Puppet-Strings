from datetime import date

import pytest

from puppet_strings.cabin_acts import CABIN_ACT_TAG, cabin_act_requests, is_cabin_act, merge
from puppet_strings.generate import GENERATED_TAG
from puppet_strings.model import Priority, Request
from puppet_strings.sheets.cabin_acts import CabinAct, parse_board, parse_title
from puppet_strings.sheets.source import LoadError
from puppet_strings.skedge.validate import validate_request

S1W1 = "Cabin Act Sorting - S1W1"
S2W1 = "Cabin Act Sorting - S2W1"


@pytest.fixture
def boards(source):
    return {
        title: parse_board(source.read(f"cabin_acts/{title}", "Board"), title)
        for title in (S1W1, S2W1)
    }


def test_parse_title_reads_the_session_and_week():
    assert parse_title("Cabin Act Sorting - S5W1", "x") == (5, 1)
    assert parse_title("cabin acts s12w3", "x") == (12, 3)
    with pytest.raises(LoadError, match="no session and week"):
        parse_title("Cabin Acts", "x")


def test_parse_board_reads_a_cabin_act_per_weekday(boards):
    acts = boards[S1W1]
    assert CabinAct("M1", "monday", "Lake Day", ("Dylan", "LIFEGUARD")) in acts
    assert (
        CabinAct("M2", "wednesday", "Fort Building", ("Vic", "Low Ropes", "Village HERO")) in acts
    )
    assert CabinAct("P4", "friday", "Tea Party", ("Sarah",)) in acts


def test_parse_board_skips_acts_with_no_heroes(boards):
    assert not [a for a in boards[S1W1] if a.cabin == "O2" and a.weekday == "tuesday"]


def test_parse_board_ignores_the_extra_columns(boards):
    assert not [a for a in boards[S1W1] if a.activity == "Never scheduled"]


def test_parse_board_needs_a_weekday_row():
    with pytest.raises(LoadError, match="heads no weekday"):
        parse_board([["title"], ["", "Somuday"], [], ["M1", "Activity", "x"]], "x")


def test_a_request_per_cabin_act_at_clinic_priority(boards, dataset):
    requests, _ = cabin_act_requests(boards, dataset)
    by_id = {r.id for r in requests}
    assert by_id == {
        "cabin_act:2026-09-14:m1",
        "cabin_act:2026-09-16:m2",
        "cabin_act:2026-09-18:p4",
        "cabin_act:2026-09-28:m1",
    }
    assert all(r.priority is Priority.CLINIC for r in requests)
    assert all(r.tags == (GENERATED_TAG, CABIN_ACT_TAG) for r in requests)


def test_a_statement_per_hero_named(boards, dataset):
    requests, _ = cabin_act_requests(boards, dataset)
    monday = next(r for r in requests if r.id == "cabin_act:2026-09-14:m1")
    assert monday.description == "M1 cabin act: Lake Day"
    assert monday.skedge.splitlines() == [
        "REQUEST staff.dylan DO 'help M1 with CA' DURING blocks.cabin_act ON 2026-09-14",
        "REQUEST ANY_1_OF staff.skills.lifeguard DO 'LIFEGUARD with M1' "
        "DURING blocks.cabin_act ON 2026-09-14",
    ]


def test_a_hero_may_be_a_person_a_category_or_a_skill(boards, dataset):
    requests, warnings = cabin_act_requests(boards, dataset)
    wednesday = next(r for r in requests if r.id == "cabin_act:2026-09-16:m2")
    assert "REQUEST staff.vic DO 'help M2 with CA'" in wednesday.skedge
    assert "ANY_1_OF staff.skills.low_ropes DO 'Low Ropes with M2'" in wednesday.skedge
    assert "ANY_1_OF staff.village_hero DO 'Village HERO with M2'" in wednesday.skedge
    assert not [w for w in warnings if "M2" in w]


def test_an_unknown_hero_warns_and_the_rest_still_import(boards, dataset):
    requests, warnings = cabin_act_requests(boards, dataset)
    assert [w for w in warnings if "'Nobody At All'" in w]
    assert "cabin_act:2026-09-17:o2" not in {r.id for r in requests}
    assert len(requests) == 4


def test_a_week_the_calendar_has_no_days_for_warns(boards, dataset):
    _, warnings = cabin_act_requests({"Cabin Acts S9W4": boards[S1W1]}, dataset)
    assert warnings == ["Cabin Acts S9W4: the Calendar sheet has no session 9 week 4"]


def test_every_request_made_is_valid_skedge(boards, dataset):
    requests, _ = cabin_act_requests(boards, dataset)
    for request in requests:
        assert validate_request(request, dataset) is not None


def test_merge_drops_every_old_cabin_act_whatever_its_date(boards, dataset):
    generated, _ = cabin_act_requests(boards, dataset)
    kept = Request("mine", "", "REQUEST staff.dylan FREE DURING blocks.lunch", Priority.LOW)
    stale = Request("cabin_act:2020-01-01:z9", "", "", Priority.CLINIC, tags=(CABIN_ACT_TAG,))
    merged = merge([kept, stale], generated)
    assert kept in merged
    assert stale not in merged
    assert [r for r in merged if is_cabin_act(r)] == generated


def test_the_same_week_on_two_sheets_is_imported_once(boards, dataset):
    doubled = {S1W1: boards[S1W1], "Cabin Act Sorting - S1W1 (copy)": boards[S1W1]}
    requests, warnings = cabin_act_requests(doubled, dataset)
    assert len(requests) == 3
    assert [w for w in warnings if "is already on" in w]


def test_no_cabin_act_block_is_an_error(boards, dataset):
    from dataclasses import replace

    blocks = {i: b for i, b in dataset.blocks.items() if i != "cabin_act"}
    with pytest.raises(LoadError, match="no 'cabin_act' block"):
        cabin_act_requests(boards, replace(dataset, blocks=blocks))


def test_the_created_date_is_the_day_the_act_falls_on(boards, dataset):
    requests, _ = cabin_act_requests(boards, dataset)
    assert {r.created for r in requests} == {
        date(2026, 9, 14),
        date(2026, 9, 16),
        date(2026, 9, 18),
        date(2026, 9, 28),
    }
