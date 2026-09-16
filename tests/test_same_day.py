"""Changing a day that is already published, moving as few people as possible."""

from dataclasses import replace
from datetime import date

import pytest

from puppet_strings.config import Config
from puppet_strings.generate import generated_requests
from puppet_strings.model import Adjustment, Offering, Priority
from puppet_strings.sheets.adjustments import adjustment_rows, on_date, parse_adjustments
from puppet_strings.sheets.source import LoadError
from puppet_strings.solver.solve import solve
from tests.build import OK, TARGET, clinic, dataset, published, request, staff

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
        adjustments=[Adjustment(TARGET, "dylan", available=False, note="sick")],
    )
    ds = replace(ds, staff={**ds.staff, "dylan": replace(ds.staff["dylan"], available=False)})
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
    away = replace(ds, staff={**ds.staff, "randy": replace(ds.staff["randy"], available=False)})
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
        ["date", "staff", "available", "ral", "note"],
        ["2026-09-16", "Vic", "", "4", "short sleep"],
        ["2026-09-16", "Alesa", "no", "", "sick"],
        ["2026-09-17", "Vic", "no", "", ""],
    ]
    adjustments = parse_adjustments(table, dataset.staff)
    assert adjustments[0] == Adjustment(date(2026, 9, 16), "vic", True, 4, "short sleep")
    assert adjustments[1].available is False and adjustments[1].ral is None
    assert {a.staff for a in on_date(adjustments, date(2026, 9, 16))} == {"vic", "alesa"}
    assert adjustment_rows(adjustments, dataset.staff)[1:] == [
        ["2026-09-16", "Alesa", "no", "", "sick"],
        ["2026-09-16", "Vic", "", "4", "short sleep"],
        ["2026-09-17", "Vic", "no", "", ""],
    ]
    assert parse_adjustments(adjustment_rows(adjustments, dataset.staff), dataset.staff)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["2026-09-16", "Nobody", "no", "", ""], "not on the Skills sheet"),
        (["2026-09-16", "Vic", "", "9", ""], "must be between 1 and 5"),
        (["2026-09-16", "Vic", "", "", "just a note"], "set `available` to no"),
        (["not-a-date", "Vic", "no", "", ""], "must be YYYY-MM-DD"),
    ],
)
def test_bad_adjustment_rows(dataset, row, message):
    table = [["date", "staff", "available", "ral", "note"], row]
    with pytest.raises(LoadError, match=message):
        parse_adjustments(table, dataset.staff)
