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
    preference,
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
CRAFT = clinic("Craft Fairy", (None, 1), (None, 1))
SOLO = clinic("Candle Making", (None, 1))

DAY_OFF = "REQUEST staff.dylan FREE DURING ALL_OF block.all"
PIN = "REQUEST staff.{who} DO activity.{what} AS_ROLE role.{role} DURING block.{block}"


def run(ds):
    return solve(ds, CONFIG)


def where(result, **fields):
    return [a for a in result.assignments if all(getattr(a, k) == v for k, v in fields.items())]


def ids(outcomes):
    return [o.id for o in outcomes]


# -- clinics and structure -------------------------------------------------------------------


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
    assert result.unsatisfied == () and result.inactive == ()
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
    assert result.feasible and ids(result.unsatisfied) == ["offering:2026-09-16:riflery:clinic_1"]


def test_unstaffable_clinic_is_reported_and_the_rest_is_scheduled():
    muay_thai = clinic("Muay Thai", ("Muay Thai", 5), ("Muay Thai", 5), category="weapons")
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY, muay_thai],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Muay Thai", ["clinic_2"])],
    )
    result = run(ds)
    assert result.feasible
    assert ids(result.unsatisfied) == ["offering:2026-09-16:muay_thai:clinic_2"]
    assert result.unsatisfied[0].priority is Priority.CLINIC
    assert where(result, activity="archery_1_2")[0].staff == "dylan"


def test_infeasible_must_happen_pair_reports_both_ids():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request("day-off", DAY_OFF, Priority.MUST_HAPPEN),
            request(
                "pin",
                PIN.format(who="dylan", what="archery_1_2", role="first", block="clinic_1"),
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
        requests=[request("day-off", DAY_OFF, Priority.MUST_HAPPEN)],
    )
    result = run(ds)
    assert result.feasible and not where(result, staff="dylan")
    assert ids(result.unsatisfied) == ["offering:2026-09-16:archery_1_2:clinic_1"]


def test_pin_and_not_do():
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
                PIN.format(who="randy", what="archery_1_2", role="first", block="clinic_1"),
                Priority.MUST_HAPPEN,
            ),
            request("off-ropes", "REQUEST staff.dylan NOT DO activity.ropes", Priority.MUST_HAPPEN),
        ],
    )
    result = run(ds)
    assert where(result, activity="archery_1_2")[0].staff == "randy"
    assert not where(result, staff="dylan", activity="gravity_zip_line")
    assert ids(result.unsatisfied) == ["offering:2026-09-16:gravity_zip_line:clinic_1"]


def test_a_clinic_runs_only_where_a_request_names_it():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        requests=[
            request("archery", "REQUEST staff.dylan DO activity.archery_1_2 DURING block.clinic_2"),
            request(
                "wish",
                "PREFER AT_LEAST 3 staff.dylan DOING activity.archery_1_2 DURING EACH_OF block.all",
            ),
        ],
    )
    result = run(ds)
    assert [(a.block, a.role) for a in where(result, activity="archery_1_2")] == [
        ("clinic_2", "first")
    ]


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
    assert ids(run(low_ral).unsatisfied) == ["offering:2026-09-16:canoe_1_2:clinic_1"]
    pinned = dataset(
        members,
        [canoe],
        offerings=[("Canoe 1 & 2", ["clinic_1"])],
        requests=[
            request(
                "pin",
                PIN.format(who="vic", what="canoe_1_2", role="lifeguard", block="clinic_1"),
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
    training = PIN.format(who="{who}", what="candle_making", role="trainee", block="clinic_1")
    ds = dataset(
        members,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"])],
        requests=[
            request("train-cam", training.format(who="cam_vl")),
            request(
                "prefer-mogee",
                "REQUEST staff.mogee DO activity.candle_making DURING block.clinic_1",
                Priority.MEDIUM,
            ),
        ],
    )
    result = run(ds)
    rows = where(result, activity="candle_making")
    assert {(a.role, a.staff) for a in rows} == {("first", "audrey"), ("scaffolded", "cam_vl")}
    assert ids(result.unsatisfied) == ["prefer-mogee"]

    no_trainer = dataset(
        [m for m in members if m.id != "audrey"],
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"])],
        requests=[request("train-cam", training.format(who="cam_vl"))],
    )
    result = run(no_trainer)
    assert ids(result.unsatisfied) == ["train-cam"]
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


# -- quoted tasks, FOR and GAP ---------------------------------------------------------------

COUNSELOR_HOURS = (
    "EACH_OF c IN staff.counselor\n"
    "morning:   REQUEST c DO 'counselor hour' FOR 1h DURING ANY_1_OF {block.clinic_1 + block.clinic_2}\n"
    "afternoon: REQUEST c DO 'counselor hour' FOR 1h DURING ANY_1_OF {block.clinic_3 + block.clinic_4}\n"
    "GAP morning TO afternoon AT_MOST 5h"
)


def test_gap_measures_real_task_times_and_moves_a_task_within_its_block():
    hours = COUNSELOR_HOURS.replace("AT_MOST 5h", "AT_LEAST 4h")
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_2"])],
        categories={"counselor": ["Dylan"]},
        requests=[
            request("counselor-hours", hours, Priority.MUST_HAPPEN),
            request(
                "not-late",
                "REQUEST staff.dylan NOT DO 'counselor hour' DURING block.clinic_4",
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


def test_gap_at_most_rejects_the_far_pair():
    ds = dataset(
        [staff("Dylan")],
        [],
        categories={"counselor": ["Dylan"]},
        requests=[
            request("counselor-hours", COUNSELOR_HOURS, Priority.MUST_HAPPEN),
            request("late", "REQUEST staff.dylan NOT DO 'counselor hour' DURING block.clinic_2"),
        ],
    )
    hour = {a.block for a in run(ds).assignments}
    assert hour == {"clinic_1", "clinic_3"}  # clinic_1 -> clinic_4 is 5h15


def test_the_same_person_sets_up_and_tears_down():
    text = (
        "ANY_1_OF p IN staff.all\n"
        "first: REQUEST p DO 'setup' DURING block.clinic_1\n"
        "last:  REQUEST p DO 'teardown' DURING block.clinic_4\n"
        "GAP first TO last AT_LEAST 0m"
    )
    ds = dataset([staff("Dylan"), staff("Sarah")], [], requests=[request("campfire", text)])
    rows = where(run(ds))
    assert sorted(a.activity for a in rows) == ["setup", "teardown"]
    assert len({a.staff for a in rows}) == 1


def test_a_task_fills_its_block_unless_for_shortens_it():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request("long", "REQUEST staff.dylan DO 'inventory' DURING block.clinic_1"),
            request("short", "REQUEST staff.dylan DO 'break' FOR 30m DURING block.clinic_2"),
        ],
    )
    rows = {a.activity: a for a in run(ds).assignments}
    assert (rows["inventory"].minutes, rows["break"].minutes) == (75, 30)
    assert rows["break"].start.strftime("%H:%M") == "10:45"


def test_two_partial_tasks_share_a_block():
    text = "REQUEST staff.dylan DO '{task}' FOR {length} DURING block.clinic_1"
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
    text = "REQUEST staff.dylan DO 'break' FOR 30m DURING block.clinic_1"
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[request("break", text, Priority.MUST_HAPPEN)],
    )
    assert ids(run(ds).unsatisfied) == ["offering:2026-09-16:archery_1_2:clinic_1"]


def test_three_breaks_in_three_distinct_blocks():
    text = (
        "REQUEST EACH_OF {staff.all - staff.director} DO 'break' FOR 30m DURING ANY_3_OF block.all"
    )
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


def test_a_quoted_task_happens_only_where_a_request_asks_for_it():
    three = request(
        "breaks",
        "REQUEST staff.sarah DO 'break' FOR 30m DURING ANY_3_OF block.all",
        Priority.MUST_HAPPEN,
    )
    wish = request("more", "PREFER AT_LEAST 5 staff.sarah DOING 'break'", Priority.HIGH, 5)
    breaks = [a for a in run(dataset([staff("Sarah")], [], requests=[three, wish])).assignments]
    assert len(breaks) == 3  # a preference cannot buy a fourth break
    typo = request("w", "PREFER AT_MOST 1 staff.sarah DOING 'breaks'", Priority.HIGH)
    with pytest.raises(RequestError, match="no request asks for 'breaks'"):
        run(dataset([staff("Sarah")], [], requests=[three, typo]))
    with pytest.raises(RequestError, match="no request asks for 'teatime'"):
        run(
            dataset(
                [staff("Sarah")],
                [],
                requests=[request("t", "REQUEST staff.sarah NOT DO 'teatime'")],
            )
        )


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
    "REQUEST EACH_OF staff.all DO 'break' FOR 30m DURING ANY_3_OF block.all",
    Priority.MUST_HAPPEN,
)


@pytest.mark.parametrize("meals", [3, 4])
def test_avoid_is_one_small_request_per_person_and_block(meals):
    avoid = request(
        "at-meals",
        "REQUEST EACH_OF staff.all NOT DO 'break' DURING EACH_OF {block.all - block.meals}",
        Priority.HIGH,
        2,
    )
    ds = dataset(
        [staff("Sarah")], [], requests=[THREE_BREAKS, avoid], blocks=blocks_with_meals(meals)
    )
    placed = sorted(a.block for a in run(ds).assignments)
    assert len(placed) == 3 and all(b.startswith("meal") for b in placed)


# -- FREE, NOT FREE and priorities ----------------------------------------------------------


def test_free_requests_outrank_a_lower_tier_task():
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request(
                "playstation",
                "REQUEST EACH_OF staff.all FREE DURING block.playstation",
                Priority.HIGH,
            ),
            request(
                "setup", "REQUEST staff.dylan DO 'setup' DURING block.playstation", Priority.MEDIUM
            ),
        ],
    )
    result = run(ds)
    assert result.assignments == ()
    assert ids(result.unsatisfied) == ["setup"]
    assert result.tier_scores[Priority.HIGH] == 2000


def test_not_free_needs_something_to_do_and_resting_is_neither():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Sarah", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[request("busy", "REQUEST staff.sarah NOT FREE DURING block.clinic_1")],
    )
    assert where(run(ds), activity="archery_1_2")[0].staff == "sarah"
    rests = {TARGET: {"sarah": frozenset({"clinic_1"})}}
    resting = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Sarah", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request("busy", "REQUEST staff.sarah NOT FREE DURING block.clinic_1"),
            request("free", "REQUEST staff.sarah FREE DURING block.clinic_1"),
        ],
        rests=rests,
    )
    result = run(resting)
    assert where(result, activity="archery_1_2")[0].staff == "dylan"
    assert ids(result.unsatisfied) == ["busy", "free"]


def test_weights_trade_within_a_tier():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK, riflery=OK)],
        [ARCHERY, RIFLERY],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Riflery", ["clinic_1"])],
        requests=[
            request(
                "likes-archery",
                "REQUEST staff.dylan DO activity.archery_1_2 DURING block.clinic_1",
                Priority.MEDIUM,
                1,
            ),
            request(
                "likes-riflery",
                "REQUEST staff.dylan DO activity.riflery DURING block.clinic_1",
                Priority.MEDIUM,
                2,
            ),
        ],
    )
    assert where(run(ds), staff="dylan")[0].activity == "riflery"


# -- amounts, metrics and past dates ---------------------------------------------------------

PREFERENCE = (
    "PREFER EACH_OF s IN staff.all DOING EACH_OF c IN activity.all MAXIMIZE metric.preference(s, c)"
)
VARIETY = "PREFER AT_MOST 1 EACH_OF staff.all DOING EACH_OF activity.all ON {(date.target - 6d) .. date.target}"


@pytest.mark.parametrize(
    ("variety_weight", "expected"), [(0.25, "archery_1_2"), (1.0, "candle_making"), (0.5, None)]
)
def test_variety_versus_preference(variety_weight, expected):
    yesterday = TARGET - timedelta(days=1)
    ds = dataset(
        [
            staff("Dylan", archery_1_2=OK, candle_making=OK),
            staff("Sarah", archery_1_2=OK, candle_making=OK),
        ],
        [ARCHERY, CANDLE],
        offerings=[("Archery 1 & 2", ["clinic_2"]), ("Candle Making", ["clinic_2"])],
        published=published(yesterday, ("Dylan", "Archery 1 & 2", "first", "clinic_1")),
        metrics=preference({("Dylan", "Archery 1 & 2"): 5, ("Dylan", "Candle Making"): 3}),
        requests=[
            request("clinic-preference", PREFERENCE, Priority.MEDIUM, 1),
            request("clinic-variety", VARIETY, Priority.MEDIUM, variety_weight),
        ],
    )
    result = run(ds)
    dylan = where(result, staff="dylan")[0].activity
    if expected is None:
        assert result.tier_scores[Priority.MEDIUM] == 500
    else:
        assert dylan == expected


def test_minimize_is_a_cost():
    ds = dataset(
        [
            staff("Dylan", archery_1_2=OK, candle_making=OK),
            staff("Sarah", archery_1_2=OK, candle_making=OK),
        ],
        [ARCHERY, CANDLE],
        offerings=[("Archery 1 & 2", ["clinic_2"]), ("Candle Making", ["clinic_2"])],
        metrics=preference(
            {("Dylan", "Archery 1 & 2"): 5, ("Dylan", "Candle Making"): 1}, default=1
        ),
        requests=[request("dislike", PREFERENCE.replace("MAXIMIZE", "MINIMIZE"), Priority.MEDIUM)],
    )
    assert where(run(ds), staff="dylan")[0].activity == "candle_making"


def test_past_assignments_count_toward_at_most():
    yesterday = TARGET - timedelta(days=1)
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    variety = request("variety", VARIETY, Priority.MEDIUM)
    prefer_dylan = request(
        "dylan", "REQUEST staff.dylan DO activity.archery_1_2 DURING block.clinic_1", Priority.LOW
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


def test_a_count_request_is_met_or_not():
    members = [
        staff("Dylan", archery_1_2=OK, candle_making=OK),
        staff("Randy", archery_1_2=OK, candle_making=OK),
    ]
    offerings = [("Archery 1 & 2", ["clinic_1"]), ("Candle Making", ["clinic_3"])]
    cap = request(
        "cap", "REQUEST AT_MOST 1 EACH_OF staff.all DOING activity.all", Priority.MUST_HAPPEN
    )
    both = request(
        "both",
        "REQUEST staff.dylan DO ANY_1_OF activity.all DURING ALL_OF {block.clinic_1 + block.clinic_3}",
    )
    ds = dataset(members, [ARCHERY, CANDLE], offerings=offerings, requests=[cap, both])
    result = run(ds)
    assert len({a.staff for a in result.assignments}) == 2
    assert ids(result.unsatisfied) == ["both"]
    exact = request("two", "REQUEST EXACTLY 2 staff.dylan DOING activity.all", Priority.MUST_HAPPEN)
    result = run(dataset(members, [ARCHERY, CANDLE], offerings=offerings, requests=[exact]))
    assert {a.staff for a in result.assignments} == {"dylan"}


def test_a_duration_amount_sums_lengths_and_past_dates_count():
    yesterday = TARGET - timedelta(days=1)
    text = "REQUEST AT_LEAST 2h staff.james DOING 'dance practice' DURING block.any_clinic ON {(date.target - 1d) .. date.target}"
    ds = dataset(
        [staff("James")],
        [],
        published=published(yesterday, ("James", "'dance practice'", None, "clinic_1", 75)),
        requests=[
            request("dance", text, Priority.MUST_HAPPEN),
            request(
                "free", "REQUEST EACH_OF staff.all FREE DURING EACH_OF block.all", Priority.HIGH
            ),
        ],
    )
    (today,) = where(run(ds), activity="dance practice")
    assert today.minutes == 75  # 75 done yesterday; one more block reaches 2h
    fresh = dataset([staff("James")], [], requests=[request("dance", text, Priority.MUST_HAPPEN)])
    assert sum(a.minutes for a in where(run(fresh), activity="dance practice")) >= 120


def test_consecutive_needs_adjacent_blocks():
    text = "REQUEST AT_LEAST 1.5h staff.james DOING 'training' DURING {{{blocks}}} CONSECUTIVE"
    adjacent = dataset(
        [staff("James")],
        [],
        requests=[
            request(
                "t",
                text.format(blocks="block.clinic_2 + block.lunch + block.clinic_3"),
                Priority.MUST_HAPPEN,
            ),
            request(
                "free", "REQUEST EACH_OF staff.all FREE DURING EACH_OF block.all", Priority.HIGH
            ),
        ],
    )
    rows = sorted(where(run(adjacent), activity="training"), key=lambda a: a.start)
    assert [(a.block, a.minutes) for a in rows] in (
        [("clinic_2", 75), ("lunch", 60)],
        [("lunch", 60), ("clinic_3", 75)],
    )
    apart = dataset(
        [staff("James")],
        [],
        requests=[request("t", text.format(blocks="block.clinic_1 + block.clinic_3"))],
    )
    assert ids(run(apart).unsatisfied) == ["t"]


def test_at_most_consecutive_breaks_up_a_run():
    members = [
        staff("Dylan", archery_1_2=OK, candle_making=OK),
        staff("Randy", archery_1_2=OK, candle_making=OK),
    ]
    ds = dataset(
        members,
        [ARCHERY, CANDLE],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "dylan",
                "REQUEST staff.dylan DO ANY_1_OF activity.all DURING ALL_OF {block.clinic_1 + block.clinic_2}",
                Priority.MEDIUM,
            ),
            request(
                "row",
                "REQUEST AT_MOST 1 EACH_OF staff.all DOING activity.all CONSECUTIVE",
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert len({a.staff for a in result.assignments}) == 2
    assert ids(result.unsatisfied) == ["dylan"]


def test_at_most_consecutive_caps_a_run_of_three_adjacent_blocks():
    """The run bound counts what a person can really hold, one assignment per block."""
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    clinics = [clinic(f"C{i}", ("Archery 1 & 2", 1)) for i in range(3)]
    offerings = [(f"C{i}", [f"clinic_{i + 1}"]) for i in range(3)]
    cap = request(
        "row",
        "REQUEST AT_MOST 2 EACH_OF staff.all DOING activity.all CONSECUTIVE",
        Priority.MUST_HAPPEN,
    )
    blocks = blocks_with_meals(0)
    # nothing but the cap keeps Dylan off all three
    greedy = request("dylan", "REQUEST AT_LEAST 3 staff.dylan DOING activity.all", Priority.MEDIUM)
    ds = dataset(members, clinics, offerings=offerings, requests=[cap, greedy], blocks=blocks)
    result = run(ds)
    assert result.feasible and ids(result.unsatisfied) == ["dylan"]
    assert len(where(result, staff="dylan")) <= 2  # the run is capped, so three is refused
    without_cap = dataset(members, clinics, offerings=offerings, requests=[greedy], blocks=blocks)
    assert len(where(run(without_cap), staff="dylan")) == 3
    loose = request(
        "row",
        "REQUEST AT_MOST 3 EACH_OF staff.all DOING activity.all CONSECUTIVE",
        Priority.MUST_HAPPEN,
    )
    only_dylan = [staff("Dylan", archery_1_2=OK)]
    ds = dataset(only_dylan, clinics, offerings=offerings, requests=[loose], blocks=blocks)
    result = run(ds)
    assert result.feasible and len(result.assignments) == 3  # a run of three is allowed


def test_prefer_at_most_pays_per_assignment_over_the_amount():
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    ds = dataset(
        members,
        [ARCHERY],
        offerings=[
            ("Archery 1 & 2", ["clinic_1"]),
            ("Archery 1 & 2", ["clinic_3"]),
            ("Archery 1 & 2", ["clinic_4"]),
        ],
        requests=[
            request(
                "balance", "PREFER AT_MOST 1 EACH_OF staff.all DOING activity.all", Priority.MEDIUM
            ),
            request(
                "dylan",
                "REQUEST staff.dylan DO activity.archery_1_2 DURING ALL_OF {block.clinic_1 + block.clinic_3}",
                Priority.MEDIUM,
                3,
            ),
        ],
    )
    result = run(ds)
    assert sorted(a.staff for a in result.assignments) == ["dylan", "dylan", "randy"]
    assert result.tier_scores[Priority.MEDIUM] == 3000 - 1000


# -- WITH and WITHOUT ------------------------------------------------------------------------


def test_not_do_with_keeps_two_staff_off_the_same_clinic():
    members = [staff("James"), staff("Paul"), staff("Sarah")]
    feud = "REQUEST staff.james NOT DO activity.all WITH staff.paul DURING EACH_OF block.all"
    ds = dataset(
        members,
        [CRAFT],
        offerings=[("Craft Fairy", ["clinic_1"])],
        requests=[request("feud", feud, Priority.HIGH, 2)],
    )
    holders = {a.staff for a in where(run(ds), activity="craft_fairy")}
    assert len(holders) == 2 and holders != {"james", "paul"}
    only_two = dataset(
        [staff("James"), staff("Paul")],
        [CRAFT],
        offerings=[("Craft Fairy", ["clinic_1"])],
        requests=[request("feud", feud, Priority.MUST_HAPPEN)],
    )
    result = run(only_two)
    assert result.feasible and ids(result.unsatisfied) == [
        "offering:2026-09-16:craft_fairy:clinic_1"
    ]


def test_a_forbidden_pair_may_still_work_in_different_blocks():
    ds = dataset(
        [staff("James"), staff("Paul")],
        [SOLO],
        offerings=[("Candle Making", ["clinic_1"]), ("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "feud",
                "REQUEST staff.james NOT DO activity.all WITH staff.paul",
                Priority.MUST_HAPPEN,
            ),
            request(
                "a",
                PIN.format(who="james", what="candle_making", role="first", block="clinic_1"),
                Priority.MUST_HAPPEN,
            ),
            request(
                "b",
                PIN.format(who="paul", what="candle_making", role="first", block="clinic_2"),
                Priority.MUST_HAPPEN,
            ),
        ],
    )
    result = run(ds)
    assert result.feasible and result.unsatisfied == ()
    assert {(a.block, a.staff) for a in where(result, activity="candle_making")} == {
        ("clinic_1", "james"),
        ("clinic_2", "paul"),
    }


def test_with_puts_two_staff_on_the_same_clinic():
    members = [staff("James"), staff("Paul"), staff("Sarah")]
    ds = dataset(
        members,
        [CRAFT, SOLO],
        offerings=[("Craft Fairy", ["clinic_1"]), ("Candle Making", ["clinic_1"])],
        requests=[
            request(
                "friends",
                "REQUEST staff.james DO activity.craft_fairy DURING block.clinic_1 WITH staff.paul",
                Priority.HIGH,
            )
        ],
    )
    assert {a.staff for a in where(run(ds), activity="craft_fairy")} == {"james", "paul"}


def test_not_do_without_means_only_together():
    members = [
        staff("Rob", gravity_zip_line_1st=OK, gravity_zip_line_2nd=OK),
        staff("Vic", gravity_zip_line_2nd=OK),
        staff("Sarah", gravity_zip_line_2nd=OK),
    ]
    ds = dataset(
        members,
        [ZIP],
        offerings=[("Gravity Zip Line", ["clinic_1"])],
        requests=[
            request(
                "rob-vic",
                "REQUEST staff.rob NOT DO activity.ropes WITHOUT staff.vic",
                Priority.MUST_HAPPEN,
            ),
            request(
                "sarah",
                PIN.format(who="sarah", what="gravity_zip_line", role="second", block="clinic_1"),
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert {a.staff for a in where(result, activity="gravity_zip_line")} == {"rob", "vic"}
    assert ids(result.unsatisfied) == ["sarah"]


def test_with_on_a_quoted_task_means_the_same_start():
    together = (
        "prep:  REQUEST staff.dylan DO 'prep' FOR 30m DURING block.clinic_1\n"
        "setup: REQUEST staff.dylan DO 'setup' FOR 30m DURING block.clinic_1 WITH staff.sarah\n"
        "GAP prep TO setup AT_LEAST 0m"
    )
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request("dylan", together, Priority.MUST_HAPPEN),
            request(
                "sarah",
                "REQUEST staff.sarah DO 'setup' FOR 30m DURING block.clinic_1",
                Priority.MUST_HAPPEN,
            ),
        ],
    )
    result = run(ds)
    assert result.feasible
    rows = {(a.staff, a.activity): a for a in result.assignments}
    assert rows["dylan", "setup"].start == rows["sarah", "setup"].start
    assert rows["sarah", "setup"].start.strftime("%H:%M") >= "09:45"


# -- conditions ------------------------------------------------------------------------------


def test_if_reads_a_published_fact():
    yesterday = TARGET - timedelta(days=1)
    text = (
        "EACH_OF s IN staff.all\n"
        "IF s NOT FREE DURING block.playstation ON {date.target - 1d}\n"
        "REQUEST s FREE DURING block.clinic_1"
    )
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    ds = dataset(
        members,
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        published=published(yesterday, ("Dylan", "'night duty'", None, "playstation")),
        requests=[
            request("rest", text, Priority.MUST_HAPPEN),
            request(
                "dylan",
                PIN.format(who="dylan", what="archery_1_2", role="first", block="clinic_1"),
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert where(result, activity="archery_1_2")[0].staff == "randy"
    assert ids(result.unsatisfied) == ["dylan"]


def test_unless_applies_only_when_the_pattern_has_no_match():
    text = (
        "UNLESS staff.director FREE DURING block.clinic_1\n"
        "REQUEST ANY_1_OF staff.office DO 'front desk' DURING block.clinic_1"
    )
    members = [staff("David", archery_1_2=OK), staff("Lisa")]
    categories = {"director": ["David"], "office": ["Lisa"]}
    idle = dataset(members, [ARCHERY], categories=categories, requests=[request("desk", text)])
    assert not where(run(idle), activity="front desk")
    busy = dataset(
        members,
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        categories=categories,
        requests=[request("desk", text)],
    )
    result = run(busy)
    assert where(result, activity="front desk")[0].staff == "lisa"
    assert result.unsatisfied == ()


def test_if_with_an_amount_over_a_run():
    text = (
        "EACH_OF s IN staff.all\n"
        "IF AT_LEAST 2 s DOING activity.all CONSECUTIVE\n"
        "REQUEST s FREE DURING block.clinic_3"
    )
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[
            ("Archery 1 & 2", ["clinic_1"]),
            ("Archery 1 & 2", ["clinic_2"]),
            ("Archery 1 & 2", ["clinic_3"]),
        ],
        requests=[request("rest", text, Priority.MUST_HAPPEN)],
    )
    result = run(ds)
    assert sorted(a.block for a in result.assignments) in (
        ["clinic_1", "clinic_2"],
        ["clinic_1", "clinic_3"],
        ["clinic_2", "clinic_3"],
    )
    assert len(result.unsatisfied) == 1


# -- the time horizon ------------------------------------------------------------------------

MAINTENANCE = "REQUEST staff.dylan DO 'archery maintenance' DURING ANY_1_OF block.all ON ANY_1_OF {2026-09-16 .. 2026-09-17}"
KEEP_FREE = request(
    "free", "REQUEST EACH_OF staff.all FREE DURING EACH_OF block.all", Priority.HIGH, 0.5
)


def test_deferrable_request_is_optional_until_its_last_date():
    tomorrow = TARGET + timedelta(days=1)
    members = [staff("Dylan")]
    first_day = dataset(members, [], requests=[request("maintenance", MAINTENANCE), KEEP_FREE])
    result = run(first_day)
    assert result.assignments == ()
    assert ids(result.deferred) == ["maintenance"] and result.unsatisfied == ()
    last_day = dataset(
        members, [], requests=[request("maintenance", MAINTENANCE), KEEP_FREE], target=tomorrow
    )
    result = run(last_day)
    assert len(where(result, activity="archery maintenance")) == 1
    assert result.deferred == () and [u.id[:5] for u in result.unsatisfied] == ["free["]


def test_deferrable_request_is_scheduled_early_when_nothing_opposes():
    ds = dataset([staff("Dylan")], [], requests=[request("m", MAINTENANCE)])
    result = run(ds)
    assert len(where(result, activity="archery maintenance")) == 1 and result.deferred == ()


def test_a_later_date_holds_nothing_for_someone_resting_through_it():
    tomorrow = TARGET + timedelta(days=1)
    rests = {tomorrow: {"dylan": frozenset(dataset([staff("Dylan")], []).blocks)}}
    ds = dataset([staff("Dylan")], [], requests=[request("m", MAINTENANCE), KEEP_FREE], rests=rests)
    result = run(ds)
    assert len(where(result, activity="archery maintenance")) == 1 and result.deferred == ()


def test_a_deferrable_amount_stays_reachable():
    text = "REQUEST AT_LEAST 2 staff.dylan DOING 'inventory' ON {2026-09-16 .. 2026-09-17}"
    tomorrow = TARGET + timedelta(days=1)
    ds = dataset(
        [staff("Dylan")], [], requests=[request("stock", text, Priority.MUST_HAPPEN), KEEP_FREE]
    )
    result = run(ds)
    assert result.assignments == () and ids(result.deferred) == ["stock"]
    rests = {tomorrow: {"dylan": frozenset(set(ds.blocks) - {"lunch"})}}
    tight = dataset(
        [staff("Dylan")],
        [],
        requests=[request("stock", text, Priority.MUST_HAPPEN), KEEP_FREE],
        rests=rests,
    )
    result = run(tight)
    assert len(where(result, activity="inventory")) == 1 and ids(result.deferred) == ["stock"]


def test_past_and_future_requests_are_inactive():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request(
                "past", "REQUEST staff.dylan DO 'x' DURING block.clinic_1 ON {date.target - 1d}"
            ),
            request("future", "REQUEST staff.dylan NOT DO 'x' ON {date.target + 1d}"),
            request(
                "empty", "REQUEST EACH_OF {staff.all - staff.dylan} DO 'x' DURING block.clinic_1"
            ),
            request("today", "REQUEST staff.dylan DO 'x' DURING block.clinic_1"),
        ],
    )
    result = run(ds)
    assert ids(result.inactive) == ["past", "future", "empty"]
    assert len(where(result, activity="x")) == 1


def test_all_of_dates_are_enforced_every_day():
    yesterday = TARGET - timedelta(days=1)
    text = "REQUEST staff.dylan DO 'x' DURING block.clinic_1 ON ALL_OF {(date.target - 1d) .. date.target}"
    done = dataset(
        [staff("Dylan")],
        [],
        published=published(yesterday, ("Dylan", "'x'", None, "clinic_1")),
        requests=[request("x", text)],
    )
    assert run(done).unsatisfied == ()
    missed = dataset([staff("Dylan")], [], requests=[request("x", text)])
    assert ids(run(missed).unsatisfied) == ["x"]


def test_invalid_request_raises():
    ds = dataset([staff("Dylan")], [], requests=[request("bad", "REQUEST staff.dylan DO 'x'")])
    with pytest.raises(RequestError, match="request 'bad'.*needs DURING"):
        run(ds)


def test_fixture_dataset_solves(dataset):
    result = solve(dataset, CONFIG)
    assert result.feasible
    assert ids(result.unsatisfied) == [
        "offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1"
    ]
    counselor_hours = [a for a in result.assignments if a.activity == "counselor hour"]
    assert len(counselor_hours) == 6 and all(a.minutes == 60 for a in counselor_hours)
    breaks = [a for a in result.assignments if a.activity == "break"]
    assert len(breaks) == 16 * 3 and all(a.minutes == 30 for a in breaks)
    assert not [
        a
        for a in result.assignments
        if a.staff == "dylan" and a.activity in dataset.activity_categories["ropes"]
    ]
    assert not [
        a
        for a in result.assignments
        if a.block == "playstation" and a.staff not in dataset.staff_categories["director"]
    ]
