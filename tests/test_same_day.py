"""Changing a day that is already published, moving as few people as possible."""

from dataclasses import replace
from datetime import date

import pytest

from puppet_strings.config import Config
from puppet_strings.generate import generated_requests
from puppet_strings.model import Adjustment, Offering, Priority, Rest
from puppet_strings.sheets.adjustments import adjustment_rows, on_date, parse_adjustments
from puppet_strings.sheets.source import LoadError
from puppet_strings.solver.solve import solve
from tests.build import BLOCKS, OK, TARGET, clinic, dataset, published, request, resting, staff

CONFIG = Config(time_limit_seconds=10, workers=4)
ARCHERY = clinic("Archery 1 & 2", ("Archery 1 & 2", 4), category="weapons")
RIFLERY = clinic("Riflery", ("Riflery", 4), category="weapons")
ROPES = clinic("Gravity Zip Line", ("Gravity Zip Line 1st", 5), category="ropes")


def day(members, activities, offerings, baseline_rows, requests=(), adjustments=()):
    """A day already published as `baseline_rows`, ready to be changed."""
    ds = dataset(members, activities, offerings=offerings, requests=requests)
    baseline = published(TARGET, *baseline_rows)[TARGET]
    return replace(ds, baseline=baseline, adjustments=tuple(adjustments))


def test_a_published_day_is_left_alone_when_nothing_has_changed():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    ds = day(
        members,
        [ARCHERY],
        [("Archery 1 & 2", ["clinic_1"])],
        [("Randy", "Archery 1 & 2", "first", "clinic_1")],
    )
    result = solve(ds, CONFIG, same_day=True)
    assert result.changes == ()
    assert [a.staff for a in result.assignments] == ["randy"]


def test_stability_beats_a_preference_but_not_a_clinic():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    prefers_dylan = request(
        "likes-dylan",
        "DURING block.any_clinic\nACROSS staff.dylan\nPREFER activity.any_clinic",
        Priority.HIGH,
    )
    ds = day(
        members,
        [ARCHERY],
        [("Archery 1 & 2", ["clinic_1"])],
        [("Randy", "Archery 1 & 2", "first", "clinic_1")],
        requests=[prefers_dylan],
    )
    # a fresh solve follows the preference; a same-day solve keeps Randy where he was
    assert [a.staff for a in solve(ds, CONFIG).assignments] == ["dylan"]
    result = solve(ds, CONFIG, same_day=True)
    assert [a.staff for a in result.assignments] == ["randy"]
    assert result.tier_scores[Priority.STABILITY] == 1000
    assert result.changes == ()


def test_someone_not_working_today_is_replaced_and_the_change_is_logged():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    ds = day(
        members,
        [ARCHERY],
        [("Archery 1 & 2", ["clinic_1"])],
        [("Dylan", "Archery 1 & 2", "first", "clinic_1")],
        adjustments=[Adjustment(TARGET, "dylan", Rest.ALL_DAY, note="sick")],
    )
    ds = replace(ds, staff={**ds.staff, "dylan": resting(ds.staff["dylan"], BLOCKS)})
    result = solve(ds, CONFIG, same_day=True)
    assert [a.staff for a in result.assignments] == ["randy"]
    gone, took_over = sorted(result.changes, key=lambda c: c.staff)
    assert gone.staff == "dylan" and gone.block == "clinic_1"
    assert [a.activity for a in gone.before] == ["archery_1_2"] and gone.after == ()
    assert took_over.staff == "randy" and took_over.before == ()
    assert [a.activity for a in took_over.after] == ["archery_1_2"]


def test_a_lower_ral_today_takes_someone_off_what_they_may_no_longer_run():
    members = [staff("Rob", gravity_zip_line_1st=OK), staff("Vic", gravity_zip_line_1st=OK)]
    rows = [("Rob", "Gravity Zip Line", "first", "clinic_1")]
    ds = day(members, [ROPES], [("Gravity Zip Line", ["clinic_1"])], rows)
    assert solve(ds, CONFIG, same_day=True).changes == ()
    tired = replace(ds, staff={**ds.staff, "rob": replace(ds.staff["rob"], ral=4)})
    result = solve(tired, CONFIG, same_day=True)
    assert [a.staff for a in result.assignments] == ["vic"]
    assert {c.staff for c in result.changes} == {"rob", "vic"}


def test_only_the_people_who_must_move_are_moved():
    members = [
        staff("Dylan", archery_1_2=OK),
        staff("Randy", riflery=OK),
        staff("Sarah", riflery=OK),
    ]
    offerings = [("Archery 1 & 2", ["clinic_1"]), ("Riflery", ["clinic_1"])]
    rows = [
        ("Dylan", "Archery 1 & 2", "first", "clinic_1"),
        ("Randy", "Riflery", "first", "clinic_1"),
    ]
    ds = day(members, [ARCHERY, RIFLERY], offerings, rows)
    away = replace(ds, staff={**ds.staff, "randy": resting(ds.staff["randy"], BLOCKS)})
    result = solve(away, CONFIG, same_day=True)
    assert {(a.staff, a.activity) for a in result.assignments} == {
        ("dylan", "archery_1_2"),
        ("sarah", "riflery"),
    }
    assert {c.staff for c in result.changes} == {"randy", "sarah"}  # Dylan hears nothing
    assert result.unsatisfied == ()


def test_staffing_a_clinic_outranks_leaving_someone_where_they_were():
    members = [staff("Dylan", archery_1_2=OK, riflery=OK), staff("Sarah", archery_1_2=OK)]
    rows = [("Dylan", "Archery 1 & 2", "first", "clinic_1")]
    ds = day(members, [ARCHERY, RIFLERY], [("Archery 1 & 2", ["clinic_1"])], rows)
    # riflery is added to the day, and only Dylan can run it
    added = replace(ds, offerings=(*ds.offerings, Offering("riflery", ("clinic_1",))))
    added = replace(added, requests=tuple(generated_requests(added)))
    result = solve(added, CONFIG, same_day=True)
    assert {(a.staff, a.activity) for a in result.assignments} == {
        ("dylan", "riflery"),
        ("sarah", "archery_1_2"),
    }
    assert result.unsatisfied == ()


def test_a_plain_solve_logs_nothing_and_ignores_the_baseline():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    ds = day(
        members,
        [ARCHERY],
        [("Archery 1 & 2", ["clinic_1"])],
        [("Randy", "Archery 1 & 2", "first", "clinic_1")],
    )
    result = solve(ds, CONFIG)
    assert result.changes == () and Priority.STABILITY not in result.tier_scores


def test_adjustments_sheet(dataset):
    table = [
        ["date", "staff", "resting", "RAL_penalty", "note"],
        ["2026-09-16", "Vic", "", "1", "short sleep"],
        ["2026-09-16", "Alesa", "all day", "", "sick"],
        ["2026-09-17", "Vic", "Morning", "2", ""],
    ]
    adjustments = parse_adjustments(table, dataset.staff)
    assert adjustments[0] == Adjustment(date(2026, 9, 16), "vic", Rest.NONE, 1, "short sleep")
    assert adjustments[1].resting is Rest.ALL_DAY and adjustments[1].ral_penalty == 0
    assert adjustments[2].resting is Rest.MORNING and adjustments[2].ral_penalty == 2
    assert {a.staff for a in on_date(adjustments, date(2026, 9, 16))} == {"vic", "alesa"}
    assert adjustment_rows(adjustments, dataset.staff)[1:] == [
        ["2026-09-16", "Alesa", "all day", "", "sick"],
        ["2026-09-16", "Vic", "", "1", "short sleep"],
        ["2026-09-17", "Vic", "morning", "2", ""],
    ]
    assert parse_adjustments(adjustment_rows(adjustments, dataset.staff), dataset.staff)


def test_a_penalty_comes_off_the_usual_ral():
    assert Adjustment(TARGET, "vic", ral_penalty=1).ral_for(5) == 4
    assert Adjustment(TARGET, "vic", ral_penalty=2).ral_for(3) == 1
    assert Adjustment(TARGET, "vic", ral_penalty=5).ral_for(3) == 0  # rules out every clinic


def test_resting_covers_the_half_of_the_day_a_block_starts_in():
    from datetime import time

    from puppet_strings.model import Block
    from puppet_strings.sheets.adjustments import resting_blocks

    blocks = [
        Block("clinic_1", time(9, 15), time(10, 30), frozenset(), frozenset()),
        Block("lunch", time(12, 0), time(13, 0), frozenset(), frozenset()),
        Block("clinic_3", time(14, 0), time(15, 15), frozenset(), frozenset()),
    ]
    midday = time(12, 0)
    morning = Adjustment(TARGET, "vic", Rest.MORNING)
    assert resting_blocks(morning, blocks, midday) == {"clinic_1"}
    afternoon = Adjustment(TARGET, "vic", Rest.AFTERNOON)
    assert resting_blocks(afternoon, blocks, midday) == {"lunch", "clinic_3"}
    assert resting_blocks(Adjustment(TARGET, "vic", Rest.ALL_DAY), blocks, midday) == {
        "clinic_1",
        "lunch",
        "clinic_3",
    }
    assert resting_blocks(Adjustment(TARGET, "vic", ral_penalty=1), blocks, midday) == frozenset()


def test_resting_half_a_day_leaves_the_other_half_alone():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    offerings = [("Archery 1 & 2", ["clinic_1"]), ("Archery 1 & 2", ["clinic_3"])]
    rows = [
        ("Dylan", "Archery 1 & 2", "first", "clinic_1"),
        ("Randy", "Archery 1 & 2", "first", "clinic_3"),
    ]
    ds = day(members, [ARCHERY], offerings, rows)
    morning_off = replace(
        ds, staff={**ds.staff, "dylan": resting(ds.staff["dylan"], BLOCKS, "morning")}
    )
    result = solve(morning_off, CONFIG, same_day=True)
    held = {(a.staff, a.block) for a in result.assignments}
    assert ("dylan", "clinic_1") not in held  # he is resting through the morning
    assert ("randy", "clinic_3") in held  # his own afternoon is untouched
    # Randy can cover the morning as well, so the clinic still runs and only he is told
    assert ("randy", "clinic_1") in held
    assert {c.staff for c in result.changes} == {"dylan", "randy"}
    assert result.unsatisfied == ()


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["2026-09-16", "Nobody", "no", "", ""], "not on the Skills sheet"),
        (["2026-09-16", "Vic", "", "9", ""], "must be between 1 and 5"),
        (["2026-09-16", "Vic", "", "", "just a note"], "give a `resting` or a `RAL_penalty`"),
        (["2026-09-16", "Vic", "later", "", ""], "must be one of"),
        (["not-a-date", "Vic", "all day", "", ""], "must be YYYY-MM-DD"),
    ],
)
def test_bad_adjustment_rows(dataset, row, message):
    table = [["date", "staff", "resting", "RAL_penalty", "note"], row]
    with pytest.raises(LoadError, match=message):
        parse_adjustments(table, dataset.staff)
