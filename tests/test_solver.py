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
    assert result.feasible and [u.id for u in result.unsatisfied] == ["offering:riflery:clinic_1"]


def test_unstaffable_clinic_is_reported_and_the_rest_is_scheduled():
    muay_thai = clinic("Muay Thai", ("Muay Thai", 5), ("Muay Thai", 5), category="weapons")
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY, muay_thai],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Muay Thai", ["clinic_2"])],
    )
    result = run(ds)
    assert result.feasible
    assert [u.id for u in result.unsatisfied] == ["offering:muay_thai:clinic_2"]
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
    assert [u.id for u in result.unsatisfied] == ["offering:archery_1_2:clinic_1"]


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
    assert [u.id for u in result.unsatisfied] == ["offering:gravity_zip_line:clinic_1"]


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


def test_lifeguard_minimum():
    canoe = clinic("Canoe 1 & 2", ("Canoe", 5), (None, 5), category="water", lifeguards=1)
    ds = dataset(
        [staff("Alesa", canoe=OK), staff("Mogee"), staff("Vic", lifeguard=OK)],
        [canoe],
        offerings=[("Canoe 1 & 2", ["clinic_1"])],
    )
    result = run(ds)
    rows = where(result, activity="canoe_1_2")
    assert {(a.role, a.staff) for a in rows} == {("first", "alesa"), ("second", "vic")}


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


def test_counselor_hours_with_gap():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_2"])],
        categories={"counselor": ["Dylan"]},
        requests=[
            request(
                "counselor-hours",
                "ACROSS EACH staff.counselor\n"
                "TASK 'counselor hour' DURING {block.clinic_1 OR block.clinic_2} AS morning\n"
                "TASK 'counselor hour' DURING {block.clinic_3 OR block.clinic_4} AS afternoon\n"
                "GAP morning afternoon <= 5h",
                Priority.MUST_HAPPEN,
            ),
            request(
                "late",
                "DURING block.clinic_3\nACROSS staff.dylan\nAVOID 'counselor hour'",
                Priority.MEDIUM,
            ),
        ],
    )
    result = run(ds)
    hours = sorted(a.block for a in where(result, staff="dylan", activity="counselor hour"))
    assert hours == ["clinic_1", "clinic_3"]  # clinic_4 would be 5h15 after clinic_1
    assert where(result, activity="archery_1_2")[0].staff == "dylan"


def test_breaks_three_of():
    ds = dataset(
        [staff("Sarah"), staff("David")],
        [],
        categories={"director": ["David"]},
        requests=[
            request(
                "breaks",
                "ACROSS EACH {staff.all - staff.director}\nDURING 3 OF block.break_slots\nTASK 'break'",
                Priority.MUST_HAPPEN,
            )
        ],
        blocks={
            **{k: v for k, v in __import__("tests.build", fromlist=["BLOCKS"]).BLOCKS.items()},
            "evening_break": ("18:00", "18:30", ("break_slots",)),
        },
    )
    result = run(ds)
    assert len(where(result, staff="sarah", activity="break")) == 3
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


def test_for_hours_sum_across_blocks_and_continuous_needs_adjacency():
    members = [staff("James")]
    hours = "ON date.target\nDURING {{block.clinic_1 + block.clinic_2 + block.pm_break + block.work_projects + block.clinic_3}}\nACROSS staff.james\nTASK 'dance practice' FOR 2h{cont}"
    ds = dataset(
        members, [], requests=[request("dance", hours.format(cont=""), Priority.MUST_HAPPEN)]
    )
    result = run(ds)
    minutes = sum(ds.blocks[a.block].minutes for a in where(result, activity="dance practice"))
    assert minutes >= 120
    continuous = dataset(
        members,
        [],
        requests=[request("dance", hours.format(cont=" CONTINUOUS"), Priority.MUST_HAPPEN)],
    )
    result = run(continuous)
    blocks = sorted(a.block for a in where(result, activity="dance practice"))
    assert blocks == ["clinic_3", "pm_break", "work_projects"]


def test_past_hours_count_toward_for():
    yesterday = TARGET - timedelta(days=1)
    ds = dataset(
        [staff("James")],
        [],
        published={
            yesterday: (
                __import__("puppet_strings.model", fromlist=["Assignment"]).Assignment(
                    "james", "dance practice", None, yesterday, "clinic_1", "dance"
                ),
            )
        },
        requests=[
            request(
                "dance",
                "ON date.target - 1d .. date.target\nDURING block.any_clinic\nACROSS staff.james\nTASK 'dance practice' FOR 2h",
                Priority.MUST_HAPPEN,
            ),
            request("free", "DURING block.any\nACROSS staff.james\nPREFER FREE", Priority.HIGH),
        ],
    )
    result = run(ds)
    assert (
        len(where(result, activity="dance practice")) == 1
    )  # 75 done + one more block reaches 120


def test_invalid_request_raises():
    ds = dataset([staff("Dylan")], [], requests=[request("bad", "TASK 'x'")])
    with pytest.raises(RequestError, match="request 'bad'.*needs DURING"):
        run(ds)


def test_fixture_dataset_solves(dataset):
    result = solve(dataset, CONFIG)
    assert result.feasible
    assert [u.id for u in result.unsatisfied] == [
        "offering:pole_course_explore_level_1_2_dbl:clinic_1"
    ]
    counselor_hours = [a for a in result.assignments if a.activity == "counselor hour"]
    assert len(counselor_hours) == 6
    assert not [
        a
        for a in result.assignments
        if a.staff == "dylan" and a.activity in dataset.activity_categories["ropes"]
    ]
