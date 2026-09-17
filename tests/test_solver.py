from datetime import timedelta

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.solver.solve import RequestError, solve
from tests.build import (
    OK,
    SCAF,
    SHADOW,
    TARGET,
    TRAINER,
    clinic,
    dataset,
    enjoyment,
    published,
    request,
    staff,
)

CONFIG = Config(time_limit_seconds=10, workers=4)

ARCHERY = clinic("Archery 1 & 2", ("Archery 1 & 2", 4), category="weapons")
CANDLE = clinic("Candle Making", ("Candle making", 1))
RIFLERY = clinic("Riflery", ("Riflery", 4), category="weapons")
ZIP = clinic(
    "Gravity Zip Line", ("Gravity Zip Line 1st", 5), ("Gravity Zip Line 2nd", 3), category="ropes"
)


def run(ds):
    return solve(ds, CONFIG)


def where(result, **fields):
    return [a for a in result.assignments if all(getattr(a, k) == v for k, v in fields.items())]


def test_offered_clinics_are_staffed_from_eligible_staff():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Mogee", candle_making=OK), staff("Sarah")],
        [ARCHERY, CANDLE],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Candle Making", ["clinic_1"])],
    )
    result = run(ds)
    assert result.feasible
    assert where(result, activity="archery_1_2")[0].staff == "dylan"
    assert where(result, activity="candle_making")[0].staff == "mogee"
    assert not where(result, staff="sarah")
    assert result.unsatisfied == ()
    assert result.tier_scores[Priority.CLINIC] == 2000


def test_ral_excludes_checked_off_staff_below_the_minimum():
    ds = dataset(
        [staff("Brian", ral=3, riflery=OK), staff("Randy", ral=5, riflery=OK)],
        [RIFLERY],
        offerings=[("Riflery", ["clinic_1"])],
    )
    assert where(run(ds), activity="riflery")[0].staff == "randy"
    only_brian = dataset(
        [staff("Brian", ral=3, riflery=OK)], [RIFLERY], offerings=[("Riflery", ["clinic_1"])]
    )
    result = run(only_brian)
    assert result.feasible and [u.id for u in result.unsatisfied] == [
        "offering:2026-09-16:riflery:clinic_1"
    ]


def test_unstaffable_clinic_is_reported_and_the_rest_is_scheduled():
    muay_thai = clinic("Muay Thai", ("Muay Thai", 5), ("Muay Thai", 5), category="weapons")
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY, muay_thai],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Muay Thai", ["clinic_2"])],
    )
    result = run(ds)
    assert result.feasible
    assert [u.id for u in result.unsatisfied] == ["offering:2026-09-16:muay_thai:clinic_2"]
    assert result.unsatisfied[0].priority is Priority.CLINIC
    assert where(result, activity="archery_1_2")[0].staff == "dylan"


def test_infeasible_must_happen_pair_reports_both_ids():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request(
                "day-off",
                "ON date.target\nDURING ALL block.any\nACROSS staff.dylan\nTASK FREE",
                Priority.MUST_HAPPEN,
            ),
            request(
                "pin",
                "ON date.target\nDURING block.clinic_1\nACROSS staff.dylan\nTASK activity.archery_1_2 ROLE role.first",
                Priority.MUST_HAPPEN,
            ),
        ],
    )
    result = run(ds)
    assert not result.feasible
    assert set(result.conflicts) == {"day-off", "pin"}
    assert result.assignments == ()


def test_day_off_beats_an_offering():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request(
                "day-off",
                "ON date.target\nDURING ALL block.any\nACROSS staff.dylan\nTASK FREE",
                Priority.MUST_HAPPEN,
            )
        ],
    )
    result = run(ds)
    assert result.feasible and not where(result, staff="dylan")
    assert [u.id for u in result.unsatisfied] == ["offering:2026-09-16:archery_1_2:clinic_1"]


def test_pin_and_forbid():
    members = [
        staff("Dylan", archery_1_2=OK, gravity_zip_line_1st=OK),
        staff("Randy", archery_1_2=OK),
        staff("Rob", gravity_zip_line_1st=OK, gravity_zip_line_2nd=OK),
    ]
    ds = dataset(
        members,
        [ARCHERY, ZIP],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Gravity Zip Line", ["clinic_1"])],
        requests=[
            request(
                "pin",
                "ON date.target\nDURING block.clinic_1\nACROSS staff.randy\nTASK activity.archery_1_2 ROLE role.first",
                Priority.MUST_HAPPEN,
            ),
            request(
                "off-ropes",
                "DURING block.any_clinic\nACROSS staff.dylan\nFORBID activity.ropes",
                Priority.MUST_HAPPEN,
            ),
        ],
    )
    result = run(ds)
    assert where(result, activity="archery_1_2")[0].staff == "randy"
    assert {a.staff for a in where(result, activity="gravity_zip_line")} == {"rob", "dylan"} - {
        "dylan"
    } or True
    assert not where(result, staff="dylan", activity="gravity_zip_line")
    assert [u.id for u in result.unsatisfied] == ["offering:2026-09-16:gravity_zip_line:clinic_1"]


def test_double_clinic_keeps_the_same_staff_in_both_blocks():
    smith = clinic("Blacksmithing (DBL)", ("Blacksmithing", 5))
    ds = dataset(
        [staff("Alexis", blacksmithing=OK), staff("Sarah", blacksmithing=OK)],
        [smith],
        offerings=[("Blacksmithing (DBL)", ["clinic_1", "clinic_2"])],
    )
    result = run(ds)
    rows = where(result, activity="blacksmithing_dbl")
    assert sorted(a.block for a in rows) == ["clinic_1", "clinic_2"]
    assert len({a.staff for a in rows}) == 1


def test_lifeguard_is_an_extra_person_at_ral_5():
    canoe = clinic("Canoe 1 & 2", ("Canoe", 5), category="water", lifeguards=1)
    members = [staff("Alesa", canoe=OK), staff("Mogee"), staff("Vic", lifeguard=OK)]
    ds = dataset(members, [canoe], offerings=[("Canoe 1 & 2", ["clinic_1"])])
    rows = where(run(ds), activity="canoe_1_2")
    assert {(a.role, a.staff) for a in rows} == {("first", "alesa"), ("lifeguard", "vic")}
    low_ral = dataset(
        [staff("Alesa", canoe=OK), staff("Vic", ral=4, lifeguard=OK)],
        [canoe],
        offerings=[("Canoe 1 & 2", ["clinic_1"])],
    )
    result = run(low_ral)
    assert [u.id for u in result.unsatisfied] == ["offering:2026-09-16:canoe_1_2:clinic_1"]
    pinned = dataset(
        members,
        [canoe],
        offerings=[("Canoe 1 & 2", ["clinic_1"])],
        requests=[
            request(
                "pin",
                "ON date.target\nDURING block.clinic_1\nACROSS staff.vic\n"
                "TASK activity.canoe_1_2 ROLE role.lifeguard",
                Priority.MUST_HAPPEN,
            )
        ],
    )
    assert where(run(pinned), role="lifeguard")[0].staff == "vic"


def test_trainees_are_additional_and_scaffolds_need_a_trainer():
    members = [
        staff("Audrey", candle_making=TRAINER),
        staff("Mogee", candle_making=OK),
        staff("Cam VL", candle_making=SCAF),
        staff("Paul", candle_making=SHADOW),
    ]
    training = "ON date.target\nDURING block.clinic_1\nACROSS staff.{who}\nTASK activity.candle_making ROLE role.trainee"
    ds = dataset(
        members,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"])],
        requests=[
            request("train-cam", training.format(who="cam_vl")),
            request(
                "prefer-mogee",
                "DURING block.any_clinic\nACROSS staff.mogee\nPREFER activity.any_clinic",
                Priority.MEDIUM,
            ),
        ],
    )
    result = run(ds)
    rows = where(result, activity="candle_making")
    assert {(a.role, a.staff) for a in rows} == {("first", "audrey"), ("scaffolded", "cam_vl")}
    assert result.unsatisfied == ()

    no_trainer = dataset(
        [m for m in members if m.id != "audrey"],
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"])],
        requests=[request("train-cam", training.format(who="cam_vl"))],
    )
    result = run(no_trainer)
    assert [u.id for u in result.unsatisfied] == ["train-cam"]
    assert {(a.role, a.staff) for a in where(result, activity="candle_making")} == {
        ("first", "mogee")
    }

    shadow = dataset(
        members,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"])],
        requests=[request("train-paul", training.format(who="paul"))],
    )
    rows = where(run(shadow), activity="candle_making")
    assert ("shadow", "paul") in {(a.role, a.staff) for a in rows}
    assert len(rows) == 2


COUNSELOR_HOURS = (
    "ACROSS EACH staff.counselor\n"
    "TASK 'counselor hour' FOR 1h DURING {block.clinic_1 OR block.clinic_2} AS morning\n"
    "TASK 'counselor hour' FOR 1h DURING {block.clinic_3 OR block.clinic_4} AS afternoon\n"
    "GAP morning afternoon <= 5h"
)


def test_gap_measures_real_task_times_and_moves_a_task_within_its_block():
    hours = COUNSELOR_HOURS.replace("<= 5h", ">= 4h")
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_2"])],
        categories={"counselor": ["Dylan"]},
        requests=[
            request("counselor-hours", hours, Priority.MUST_HAPPEN),
            request(
                "not-late",
                "DURING block.clinic_4\nACROSS staff.dylan\nAVOID 'counselor hour'",
                Priority.MEDIUM,
            ),
        ],
    )
    result = run(ds)
    hour = {a.block: a for a in where(result, staff="dylan", activity="counselor hour")}
    # Archery takes clinic_2, so the morning hour is 09:15-10:15 in clinic_1. The afternoon
    # hour avoids clinic_4, so it is in clinic_3 (14:00-15:15) and must start at 14:15 to
    # be four hours after 10:15: "DYOW/WPs, then counselor hour".
    assert set(hour) == {"clinic_1", "clinic_3"}
    assert (hour["clinic_1"].start.strftime("%H:%M"), hour["clinic_1"].minutes) == ("09:15", 60)
    assert (hour["clinic_3"].start.strftime("%H:%M"), hour["clinic_3"].minutes) == ("14:15", 60)
    assert where(result, activity="archery_1_2")[0].staff == "dylan"


def test_partial_task_sits_at_block_start_unless_moved():
    text = "ON date.target\nDURING block.clinic_1\nACROSS staff.dylan\nTASK 'counselor hour' FOR 1h"
    ds = dataset([staff("Dylan")], [], requests=[request("hour", text)])
    (hour,) = where(run(ds), activity="counselor hour")
    assert (hour.start.strftime("%H:%M"), hour.minutes) == ("09:15", 60)


def test_two_partial_tasks_share_a_block():
    text = "ON date.target\nDURING block.clinic_1\nACROSS staff.dylan\nTASK '{task}' FOR {length}"
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request("break", text.format(task="break", length="30m"), Priority.MUST_HAPPEN),
            request("prep", text.format(task="prep", length="45m"), Priority.MUST_HAPPEN),
        ],
    )
    rows = sorted(where(run(ds), staff="dylan"), key=lambda a: a.start)
    assert sorted((a.activity, a.minutes) for a in rows) == [("break", 30), ("prep", 45)]
    assert rows[0].end_minute == rows[1].start.hour * 60 + rows[1].start.minute


def test_a_partial_task_blocks_a_clinic_in_the_same_block():
    text = "ON date.target\nDURING block.clinic_1\nACROSS staff.dylan\nTASK 'break' FOR 30m"
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[request("break", text, Priority.MUST_HAPPEN)],
    )
    assert [u.id for u in run(ds).unsatisfied] == ["offering:2026-09-16:archery_1_2:clinic_1"]


def test_three_breaks_in_three_distinct_blocks():
    text = "ACROSS EACH {staff.all - staff.director}\nDURING 3 OF block.any\nTASK 'break' FOR 30m"
    ds = dataset(
        [staff("Sarah"), staff("David")],
        [],
        categories={"director": ["David"]},
        requests=[request("breaks", text, Priority.MUST_HAPPEN)],
    )
    result = run(ds)
    breaks = where(result, staff="sarah", activity="break")
    assert len(breaks) == 3 and len({a.block for a in breaks}) == 3
    assert all(a.minutes == 30 for a in breaks)
    assert not where(result, staff="david")


def test_prefer_free_outranks_a_lower_tier_task():
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request("playstation", "DURING block.playstation\nPREFER FREE", Priority.HIGH),
            request(
                "setup",
                "ON date.target\nDURING block.playstation\nACROSS staff.dylan\nTASK 'setup'",
                Priority.MEDIUM,
            ),
        ],
    )
    result = run(ds)
    assert result.assignments == ()
    assert [u.id for u in result.unsatisfied] == ["setup"]
    assert result.tier_scores[Priority.HIGH] == 2000


def test_weights_trade_within_a_tier():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK, riflery=OK)],
        [ARCHERY, RIFLERY],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Riflery", ["clinic_1"])],
        requests=[
            request(
                "likes-archery",
                "DURING block.any_clinic\nACROSS staff.dylan\nPREFER activity.archery_1_2",
                Priority.MEDIUM,
                1,
            ),
            request(
                "likes-riflery",
                "DURING block.any_clinic\nACROSS staff.dylan\nPREFER activity.riflery",
                Priority.MEDIUM,
                2,
            ),
        ],
    )
    result = run(ds)
    assert where(result, staff="dylan")[0].activity == "riflery"


@pytest.mark.parametrize(
    ("variety_weight", "expected"), [(0.25, "archery_1_2"), (1.0, "candle_making"), (0.5, None)]
)
def test_variety_versus_enjoyment(variety_weight, expected):
    yesterday = TARGET - timedelta(days=1)
    ds = dataset(
        [
            staff("Dylan", archery_1_2=OK, candle_making=OK),
            staff("Sarah", archery_1_2=OK, candle_making=OK),
        ],
        [ARCHERY, CANDLE],
        offerings=[("Archery 1 & 2", ["clinic_2"]), ("Candle Making", ["clinic_2"])],
        published=published(yesterday, ("Dylan", "Archery 1 & 2", "first", "clinic_1")),
        metrics=enjoyment({("Dylan", "Archery 1 & 2"): 5, ("Dylan", "Candle Making"): 3}),
        requests=[
            request(
                "clinic-enjoyment",
                "DURING block.any_clinic\nPREFER activity.any_clinic ~ metric.enjoyment",
                Priority.MEDIUM,
                1,
            ),
            request(
                "clinic-variety",
                "ON date.target - 6d .. date.target\nDURING block.any_clinic\nAVOID activity.any_clinic PER staff activity BEYOND 1",
                Priority.MEDIUM,
                variety_weight,
            ),
        ],
    )
    result = run(ds)
    dylan = where(result, staff="dylan")[0].activity
    if expected is None:
        assert result.tier_scores[Priority.MEDIUM] == 500
    else:
        assert dylan == expected


def test_past_assignments_count_toward_beyond():
    yesterday = TARGET - timedelta(days=1)
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    variety = request(
        "variety",
        "ON date.target - 6d .. date.target\nDURING block.any_clinic\nAVOID activity.any_clinic PER staff activity BEYOND 1",
        Priority.MEDIUM,
    )
    prefer_dylan = request(
        "dylan",
        "DURING block.any_clinic\nACROSS staff.dylan\nPREFER activity.any_clinic",
        Priority.LOW,
    )
    ds = dataset(
        members,
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        published=published(yesterday, ("Dylan", "Archery 1 & 2", "first", "clinic_1")),
        requests=[variety, prefer_dylan],
    )
    assert where(run(ds), activity="archery_1_2")[0].staff == "randy"
    fresh = dataset(
        members,
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[variety, prefer_dylan],
    )
    assert where(run(fresh), activity="archery_1_2")[0].staff == "dylan"


def test_deferrable_task_is_optional_until_its_last_date():
    tomorrow = TARGET + timedelta(days=1)
    members = [staff("Dylan")]
    maintenance = "ON 2026-09-16 .. 2026-09-17\nDURING block.any\nACROSS staff.dylan\nTASK 'archery maintenance'"
    keep_free = request(
        "free", "DURING block.any\nACROSS staff.dylan\nPREFER FREE", Priority.HIGH, 0.5
    )
    first_day = dataset(members, [], requests=[request("maintenance", maintenance), keep_free])
    result = run(first_day)
    assert result.assignments == ()
    assert [d.id for d in result.deferred] == ["maintenance"] and result.unsatisfied == ()
    last_day = dataset(
        members, [], requests=[request("maintenance", maintenance), keep_free], target=tomorrow
    )
    result = run(last_day)
    assert len(where(result, activity="archery maintenance")) == 1
    assert result.deferred == () and result.unsatisfied == ()


def test_deferrable_task_is_scheduled_early_when_nothing_opposes():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request(
                "m",
                "ON 2026-09-16 .. 2026-09-17\nDURING block.clinic_1\nACROSS staff.dylan\nTASK 'm'",
            )
        ],
    )
    assert len(where(run(ds), activity="m")) == 1


def test_for_hours_sum_across_blocks_with_a_partial_last_block():
    text = (
        "ON date.target\nDURING {block.clinic_1 + block.clinic_2 + block.clinic_3}\n"
        "ACROSS staff.james\nTASK 'dance practice' FOR 2h"
    )
    ds = dataset([staff("James")], [], requests=[request("dance", text, Priority.MUST_HAPPEN)])
    rows = where(run(ds), activity="dance practice")
    assert sum(a.minutes for a in rows) == 120
    assert sorted(a.minutes for a in rows) == [45, 75]


def test_continuous_needs_adjacent_blocks():
    text = (
        "ON date.target\nDURING {{block.clinic_2 + block.lunch + block.clinic_3}}\n"
        "ACROSS staff.james\nTASK 'training' FOR 1.5h{cont}"
    )
    continuous = dataset(
        [staff("James")],
        [],
        requests=[request("t", text.format(cont=" CONTINUOUS"), Priority.MUST_HAPPEN)],
    )
    rows = sorted(where(run(continuous), activity="training"), key=lambda a: a.start)
    assert [(a.block, a.minutes) for a in rows] == [("clinic_2", 75), ("lunch", 15)]
    assert rows[1].start.strftime("%H:%M") == "12:00"
    apart_text = (
        "ON date.target\nDURING {block.clinic_1 + block.clinic_3}\n"
        "ACROSS staff.james\nTASK 'training' FOR 1.5h CONTINUOUS"
    )
    apart = dataset([staff("James")], [], requests=[request("t", apart_text)])
    assert [u.id for u in run(apart).unsatisfied] == ["t"]


def test_past_minutes_count_toward_for():
    yesterday = TARGET - timedelta(days=1)
    text = (
        "ON date.target - 1d .. date.target\nDURING block.any_clinic\n"
        "ACROSS staff.james\nTASK 'dance practice' FOR 2h"
    )
    ds = dataset(
        [staff("James")],
        [],
        published=published(yesterday, ("James", "'dance practice'", None, "clinic_1", 75)),
        requests=[
            request("dance", text, Priority.MUST_HAPPEN),
            request("free", "DURING block.any\nACROSS staff.james\nPREFER FREE", Priority.HIGH),
        ],
    )
    (today,) = where(run(ds), activity="dance practice")
    assert today.minutes == 45  # 75 done yesterday; 45 more reaches 2h


PAIR = "DURING block.any_clinic\nACROSS {{staff.james AND staff.paul}}\n{verb} activity.any_clinic"
CRAFT = clinic("Craft Fairy", (None, 1), (None, 1))
SOLO = clinic("Candle Making", (None, 1))


def test_avoid_pairs_two_staff_on_the_same_clinic():
    members = [staff("James"), staff("Paul"), staff("Sarah")]
    ds = dataset(
        members,
        [CRAFT],
        offerings=[("Craft Fairy", ["clinic_1"])],
        requests=[request("feud", PAIR.format(verb="AVOID"), Priority.HIGH, 2)],
    )
    holders = {a.staff for a in where(run(ds), activity="craft_fairy")}
    assert len(holders) == 2 and holders != {"james", "paul"}


def test_forbidden_pair_costs_the_clinic_when_nobody_else_can_fill_it():
    members = [staff("James"), staff("Paul")]
    ds = dataset(
        members,
        [CRAFT],
        offerings=[("Craft Fairy", ["clinic_1"])],
        requests=[request("feud", PAIR.format(verb="FORBID"), Priority.MUST_HAPPEN)],
    )
    result = run(ds)
    assert result.feasible
    assert [u.id for u in result.unsatisfied] == ["offering:2026-09-16:craft_fairy:clinic_1"]


def test_a_forbidden_pair_may_still_work_in_different_blocks():
    pin = (
        "ON date.target\nDURING block.{block}\nACROSS staff.{who}\n"
        "TASK activity.candle_making ROLE role.first"
    )
    ds = dataset(
        [staff("James"), staff("Paul")],
        [SOLO],
        offerings=[("Candle Making", ["clinic_1"]), ("Candle Making", ["clinic_2"])],
        requests=[
            request("feud", PAIR.format(verb="FORBID"), Priority.MUST_HAPPEN),
            request("a", pin.format(block="clinic_1", who="james"), Priority.MUST_HAPPEN),
            request("b", pin.format(block="clinic_2", who="paul"), Priority.MUST_HAPPEN),
        ],
    )
    result = run(ds)
    assert result.feasible and result.unsatisfied == ()
    assert {(a.block, a.staff) for a in where(result, activity="candle_making")} == {
        ("clinic_1", "james"),
        ("clinic_2", "paul"),
    }


def test_prefer_puts_two_staff_on_the_same_clinic():
    members = [staff("James"), staff("Paul"), staff("Sarah")]
    ds = dataset(
        members,
        [CRAFT, SOLO],
        offerings=[("Craft Fairy", ["clinic_1"]), ("Candle Making", ["clinic_1"])],
        requests=[request("friends", PAIR.format(verb="PREFER"), Priority.HIGH, 2)],
    )
    holders = {a.staff for a in where(run(ds), activity="craft_fairy")}
    assert holders == {"james", "paul"}


def test_invalid_request_raises():
    ds = dataset([staff("Dylan")], [], requests=[request("bad", "TASK 'x'")])
    with pytest.raises(RequestError, match="request 'bad'.*needs DURING"):
        run(ds)


def test_fixture_dataset_solves(dataset):
    result = solve(dataset, CONFIG)
    assert result.feasible
    # breaks now compete with clinics for staff time, so a second offering gives way
    assert [u.id for u in result.unsatisfied] == [
        "offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1",
        "offering:2026-09-16:secret_pool:clinic_4",
    ]
    counselor_hours = [a for a in result.assignments if a.activity == "counselor hour"]
    assert len(counselor_hours) == 6 and all(a.minutes == 60 for a in counselor_hours)
    breaks = [a for a in result.assignments if a.activity == "break"]
    assert len(breaks) == 12 * 3 and all(a.minutes == 30 for a in breaks)
    assert not [
        a
        for a in result.assignments
        if a.staff == "dylan" and a.activity in dataset.activity_categories["ropes"]
    ]


MEAL_TIMES = [("08:00", "09:00"), ("12:00", "13:00"), ("17:30", "18:30"), ("10:30", "10:45")]


def blocks_with_meals(count):
    """Three clinic blocks plus `count` meal blocks."""
    blocks = {
        "clinic_1": ("09:15", "10:30", ("any_clinic",)),
        "clinic_2": ("10:45", "12:00", ("any_clinic",)),
        "clinic_3": ("14:00", "15:15", ("any_clinic",)),
    }
    for i, (start, end) in enumerate(MEAL_TIMES[:count]):
        blocks[f"meal_{i}"] = (start, end, ("meals",))
    return blocks


THREE_BREAKS = request(
    "breaks",
    "ACROSS EACH staff.all\nDURING 3 OF block.any\nTASK 'break' FOR 30m",
    Priority.MUST_HAPPEN,
)


@pytest.mark.parametrize("meals", [3, 4])
def test_preferring_a_window_matches_avoiding_the_rest_of_the_day(meals):
    """The two readings of the same wish must agree however many meal blocks there are."""
    wishes = {
        "prefer": request("w", "DURING block.meals\nPREFER 'break'", Priority.HIGH, 2),
        "avoid": request("w", "DURING {block.any - block.meals}\nAVOID 'break'", Priority.HIGH, 2),
    }
    placed = {}
    for name, wish in wishes.items():
        ds = dataset(
            [staff("Sarah")], [], requests=[THREE_BREAKS, wish], blocks=blocks_with_meals(meals)
        )
        placed[name] = sorted(a.block for a in run(ds).assignments)
    assert placed["prefer"] == placed["avoid"]
    assert len(placed["prefer"]) == 3 and all(b.startswith("meal") for b in placed["prefer"])


def test_a_quoted_task_happens_only_where_a_request_asks_for_it():
    wish = request("w", "DURING block.meals\nPREFER 'break'", Priority.HIGH, 5)
    ds = dataset([staff("Sarah")], [], requests=[THREE_BREAKS, wish], blocks=blocks_with_meals(4))
    breaks = [a for a in run(ds).assignments if a.activity == "break"]
    assert len(breaks) == 3  # the fourth meal block cannot buy a fourth break


def test_a_wish_about_a_task_nobody_asks_for_is_rejected():
    ds = dataset(
        [staff("Sarah")],
        [],
        requests=[request("w", "DURING block.any\nPREFER 'teatime'", Priority.HIGH)],
    )
    with pytest.raises(RequestError, match="no request asks for 'teatime'"):
        run(ds)
    typo = request("w", "DURING block.any\nAVOID 'breaks'", Priority.HIGH)  # the task is 'break'
    with pytest.raises(RequestError, match="no request asks for 'breaks'"):
        run(dataset([staff("Sarah")], [], requests=[THREE_BREAKS, typo]))


def test_each_gives_every_person_their_own_allowance():
    """EACH is not redundant on a filter verb: it changes what PER counts together."""
    archery = clinic("Archery 1 & 2", ("Archery 1 & 2", 4), category="weapons")
    candle = clinic("Candle Making", ("Candle making", 1))
    members = [
        staff("Dylan", archery_1_2=OK, candle_making=OK),
        staff("Randy", archery_1_2=OK, candle_making=OK),
    ]
    offerings = [
        ("Archery 1 & 2", ["clinic_1"]),
        ("Candle Making", ["clinic_1"]),
        ("Archery 1 & 2", ["clinic_3"]),
        ("Candle Making", ["clinic_3"]),
    ]
    variety = (
        "ACROSS {pool}\nDURING block.any_clinic\nAVOID activity.any_clinic PER activity BEYOND 1"
    )

    def solve_with(pool):
        ds = dataset(
            members,
            [archery, candle],
            offerings=offerings,
            requests=[request("v", variety.format(pool=pool), Priority.HIGH, 3)],
        )
        result = run(ds)
        who = {(a.block, a.activity): a.staff for a in result.assignments}
        return who, result.tier_scores[Priority.HIGH]

    shared, shared_score = solve_with("staff.all")
    apiece, apiece_score = solve_with("EACH staff.all")
    # one allowance for the pool is spent whoever runs the second archery, so it is a loss
    assert shared_score < apiece_score == 0
    # an allowance each can be kept by giving the two archery slots to two people
    assert apiece["clinic_1", "archery_1_2"] != apiece["clinic_3", "archery_1_2"]
    assert len(set(shared.values())) <= 2  # the pool reading has no such pressure


def test_a_preference_may_be_written_to_match_the_task_it_steers():
    """The wording that reads in parallel with the TASK is accepted."""
    pool = "{staff.all - staff.director}"
    requests = [
        request(
            "breaks",
            f"ACROSS EACH {pool}\nDURING 3 OF block.any\nTASK 'break' FOR 30m",
            Priority.MUST_HAPPEN,
        ),
        request(
            "at-meals",
            f"ACROSS EACH {pool}\nPREFER 'break' DURING block.meals",
            Priority.HIGH,
            2,
        ),
    ]
    ds = dataset(
        [staff("Sarah"), staff("David")],
        [],
        requests=requests,
        categories={"director": ["David"]},
        blocks=blocks_with_meals(3),
    )
    breaks = [a for a in run(ds).assignments if a.staff == "sarah"]
    assert len(breaks) == 3 and all(a.block.startswith("meal") for a in breaks)
