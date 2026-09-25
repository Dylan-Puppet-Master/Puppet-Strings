from dataclasses import replace
from datetime import timedelta

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Priority, Request
from puppet_strings.solver.solve import Resolutions, solve
from tests.build import (
    BLOCKS,
    OK,
    SCAF,
    SHADOW,
    TARGET,
    TRAINER,
    buddies,
    cabin_act,
    clinic,
    dataset,
    preference,
    published,
    request,
    staff,
)
from tests.conftest import family_camp

CONFIG = Config(tier_seconds_limit=10, workers=4)

ARCHERY = clinic("Archery 1 & 2", ("Archery 1 & 2", 4), category="weapons")
CANDLE = clinic("Candle Making", ("Candle making", 1))
RIFLERY = clinic("Riflery", ("Riflery", 4), category="weapons")
ZIP = clinic(
    "Gravity Zip Line", ("Gravity Zip Line 1st", 5), ("Gravity Zip Line 2nd", 3), category="ropes"
)
CRAFT = clinic("Craft Fairy", (None, 1), (None, 1))
SOLO = clinic("Candle Making", (None, 1))

DAY_OFF = "REQUEST staff.dylan FREE DURING ALL blocks"
PIN = "REQUEST staff.{who} DO activities.clinics.{what} AS_ROLE roles.{role} DURING blocks.{block}"


def run(ds):
    return solve(ds, CONFIG)


def where(result, **fields):
    return [a for a in result.assignments if all(getattr(a, k) == v for k, v in fields.items())]


def ids(outcomes):
    return [o.id for o in outcomes]


def requests_of(outcomes):
    """The requests behind the outcomes, once each.

    A generated clinic request asks for each position separately (`AS_ROLE EACH`), so
    an unstaffable clinic is reported once per position, as `<id>[first]`, `<id>[second]`.
    These tests are about which clinic could not be staffed, not about how many positions
    it has.
    """
    return list(dict.fromkeys(o.id.split("[")[0] for o in outcomes))


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
    assert requests_of(result.unsatisfied) == ["offering:2026-09-16:muay_thai:clinic_2"]
    # one line per clinic, not per position: an instance fills all of its positions or none
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
            request(
                "off-ropes",
                "REQUEST staff.dylan NOT DO ANY activities.clinics.ropes",
                Priority.MUST_HAPPEN,
            ),
        ],
    )
    result = run(ds)
    assert where(result, activity="archery_1_2")[0].staff == "randy"
    assert not where(result, staff="dylan", activity="gravity_zip_line")
    assert requests_of(result.unsatisfied) == ["offering:2026-09-16:gravity_zip_line:clinic_1"]


def test_a_clinic_runs_only_where_a_request_names_it():
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        requests=[
            request(
                "archery",
                "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING blocks.clinic_2",
            ),
            request(
                "wish",
                "PREFER staff.dylan DO activities.clinics.archery_1_2 DURING AT_LEAST 3 blocks",
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
    assert requests_of(run(low_ral).unsatisfied) == ["offering:2026-09-16:canoe_1_2:clinic_1"]
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
                "REQUEST staff.mogee DO activities.clinics.candle_making DURING blocks.clinic_1",
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
    "EACH c IN staff.counselor\n"
    "morning:   REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2}\n"
    "afternoon: REQUEST c DO 'counselor hour' FOR EXACTLY 1h DURING ANY 1 {blocks.clinic_3 + blocks.clinic_4}\n"
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
                "REQUEST staff.dylan NOT DO 'counselor hour' DURING blocks.clinic_4",
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
            request("late", "REQUEST staff.dylan NOT DO 'counselor hour' DURING blocks.clinic_2"),
        ],
    )
    hour = {a.block for a in run(ds).assignments}
    assert hour == {"clinic_1", "clinic_3"}  # clinic_1 -> clinic_4 is 5h15


MEETINGS = (
    "first: REQUEST staff.dylan DO 'meeting' FOR EXACTLY 1h\n"
    "DURING ANY 1 blocks.all_clinics ON ANY 1 {{{yesterday} .. {target}}}\n"
    "second: REQUEST staff.dylan DO 'meeting' FOR EXACTLY 1h DURING ANY 1 blocks.all_clinics\n"
    "GAP first TO second AT_LEAST {gap}"
)


def meetings(gap: str):
    """Two meetings, the first of which may already have happened yesterday afternoon."""
    yesterday = TARGET - timedelta(days=1)
    text = MEETINGS.format(yesterday=yesterday, target=TARGET, gap=gap)
    return dataset(
        [staff("Dylan")],
        [],
        requests=[request("meetings", text, Priority.MUST_HAPPEN)],
        published=published(yesterday, ("Dylan", "'meeting'", None, "clinic_4", 60)),
    )


def test_a_gap_is_measured_from_the_day_the_first_meeting_was_published_on():
    """A gap reaches back into a published day: 16:45 yesterday is where it is counted from.

    The first meeting is allowed to be yesterday's, which it is, so the second must be at
    least a day and a half after 16:45 — and today has no such block, so nothing today can
    hold it.
    """
    result = solve(meetings("36h"), CONFIG)
    assert not result.feasible and result.conflicts == ("meetings",)


def test_the_same_gap_is_met_when_the_published_meeting_is_far_enough_back():
    """16:45 yesterday to 15:45 today is 23 hours, which is room enough for a 20-hour gap."""
    result = solve(meetings("20h"), CONFIG)
    assert result.feasible and ids(result.unsatisfied) == []
    # yesterday's meeting answers `first`, so only the second one is scheduled today
    (today,) = [a for a in result.assignments if a.activity == "meeting"]
    assert today.block == "clinic_4" and today.start.strftime("%H:%M") == "15:45"


def test_the_same_person_sets_up_and_tears_down():
    text = (
        "ANY 1 p IN staff\n"
        "first: REQUEST p DO 'setup' DURING blocks.clinic_1\n"
        "last:  REQUEST p DO 'teardown' DURING blocks.clinic_4\n"
        "GAP first TO last AT_LEAST 0m"
    )
    ds = dataset([staff("Dylan"), staff("Sarah")], [], requests=[request("campfire", text)])
    rows = where(run(ds))
    assert sorted(a.activity for a in rows) == ["setup", "teardown"]
    assert len({a.staff for a in rows}) == 1


def test_a_bound_name_can_be_added_into_a_set():
    """ "Charlton needs to do something with either Dylan or Donny" is one request."""
    text = (
        "ANY 1 videographer IN {staff.dylan + staff.donny}\n"
        "REQUEST ALL {staff.charlton + videographer}\n"
        "DO 'Video KM Rope Swing' FOR EXACTLY 30m DURING blocks.clinic_1"
    )
    ds = dataset(
        [staff("Charlton"), staff("Dylan"), staff("Donny")],
        [],
        requests=[request("video", text)],
    )
    rows = [a for a in run(ds).assignments if a.activity == "Video KM Rope Swing"]
    who = {a.staff for a in rows}
    assert "charlton" in who  # named outright, so always
    assert len(who & {"dylan", "donny"}) == 1  # and one of the two, the solver's pick
    assert len(who) == 2


def test_a_bound_name_added_into_a_set_is_the_same_person_throughout():
    """The binding is one choice for the whole request, wherever the name turns up."""
    text = (
        "ANY 1 videographer IN {staff.dylan + staff.donny}\n"
        "morning: REQUEST ALL {staff.charlton + videographer}\n"
        "  DO 'film' FOR EXACTLY 30m DURING blocks.clinic_1\n"
        "after: REQUEST videographer DO 'edit' FOR EXACTLY 30m DURING blocks.clinic_3"
    )
    ds = dataset(
        [staff("Charlton"), staff("Dylan"), staff("Donny")],
        [],
        requests=[request("video", text)],
    )
    rows = run(ds).assignments
    filming = {a.staff for a in rows if a.activity == "film"} - {"charlton"}
    editing = {a.staff for a in rows if a.activity == "edit"}
    assert filming == editing and len(editing) == 1


def test_a_group_chosen_in_place_is_the_same_as_a_binding_line():
    """`(ANY 1 …)` added into a set brings one of its members, as a bound name would."""
    text = (
        "REQUEST ALL {staff.charlton + (ANY 1 {staff.dylan + staff.donny})}\n"
        "DO 'Video KM Rope Swing' FOR EXACTLY 30m DURING blocks.clinic_1"
    )
    ds = dataset(
        [staff("Charlton"), staff("Dylan"), staff("Donny")],
        [],
        requests=[request("video", text)],
    )
    rows = [a for a in run(ds).assignments if a.activity == "Video KM Rope Swing"]
    who = {a.staff for a in rows}
    assert "charlton" in who
    assert len(who & {"dylan", "donny"}) == 1
    assert len(who) == 2


@pytest.mark.parametrize("dylan_is_away", [False, True])
def test_a_group_inside_any_is_chosen_as_one(dylan_is_away):
    """`ANY 1 {x + (ALL {y + z})}` is x alone, or else y and z together."""
    text = (
        "REQUEST ANY 1 {staff.dylan + (ALL {staff.donny + staff.vic})}\n"
        "DO 'garbage' FOR EXACTLY 30m DURING blocks.clinic_1"
    )
    requests = [request("garbage", text, Priority.MUST_HAPPEN)]
    if dylan_is_away:
        requests.append(request("away", DAY_OFF, Priority.MUST_HAPPEN))
    ds = dataset([staff("Dylan"), staff("Donny"), staff("Vic")], [], requests=requests)
    who = {a.staff for a in run(ds).assignments if a.activity == "garbage"}
    assert who in ({"dylan"}, {"donny", "vic"})
    if dylan_is_away:
        assert who == {"donny", "vic"}


def test_each_of_a_group_is_one_request_for_the_group():
    text = (
        "REQUEST EACH {staff.dylan + (ALL {staff.donny + staff.vic})}\n"
        "DO 'meeting' FOR EXACTLY 30m DURING ANY 1 {blocks.clinic_1 + blocks.clinic_3}"
    )
    ds = dataset([staff("Dylan"), staff("Donny"), staff("Vic")], [], requests=[request("m", text)])
    rows = [a for a in run(ds).assignments if a.activity == "meeting"]
    assert {a.staff for a in rows} == {"dylan", "donny", "vic"}
    blocks = {a.staff: a.block for a in rows}
    assert blocks["donny"] == blocks["vic"]  # together, in one copy


def test_a_task_fills_its_block_unless_for_shortens_it():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request("long", "REQUEST staff.dylan DO 'inventory' DURING blocks.clinic_1"),
            request(
                "short", "REQUEST staff.dylan DO 'break' FOR EXACTLY 30m DURING blocks.clinic_2"
            ),
        ],
    )
    rows = {a.activity: a for a in run(ds).assignments}
    assert (rows["inventory"].minutes, rows["break"].minutes) == (75, 30)
    assert rows["break"].start.strftime("%H:%M") == "10:45"


def test_two_partial_tasks_share_a_block():
    text = "REQUEST staff.dylan DO '{task}' FOR EXACTLY {length} DURING blocks.clinic_1"
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
    text = "REQUEST staff.dylan DO 'break' FOR EXACTLY 30m DURING blocks.clinic_1"
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[request("break", text, Priority.MUST_HAPPEN)],
    )
    assert ids(run(ds).unsatisfied) == ["offering:2026-09-16:archery_1_2:clinic_1"]


def test_three_breaks_in_three_distinct_blocks():
    text = "REQUEST EACH {staff - staff.director} DO 'break' FOR EXACTLY 30m DURING ANY 3 blocks"
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
        "REQUEST staff.sarah DO 'break' FOR EXACTLY 30m DURING ANY 3 blocks",
        Priority.MUST_HAPPEN,
    )
    wish = request(
        "more", "PREFER staff.sarah DO 'break' DURING AT_LEAST 5 blocks", Priority.HIGH, 5
    )
    breaks = [a for a in run(dataset([staff("Sarah")], [], requests=[three, wish])).assignments]
    assert len(breaks) == 3  # a preference cannot buy a fourth break
    typo = request("w", "PREFER staff.sarah DO 'breaks' DURING AT_MOST 1 blocks", Priority.HIGH)
    result = run(dataset([staff("Sarah")], [], requests=[three, typo]))
    assert list(left_out(result)) == ["w"]  # and the rest is solved
    assert "no request asks for 'breaks'" in left_out(result)["w"]
    assert len(result.assignments) == 3
    alone = [request("t", "REQUEST staff.sarah NOT DO 'teatime'")]
    why = left_out(run(dataset([staff("Sarah")], [], requests=alone)))["t"]
    assert "no request asks for 'teatime'" in why


def left_out(result) -> dict[str, str]:
    """The requests a solve left out as invalid, with why."""
    found = {}
    for note in result.notes:
        if note.startswith("Left out "):
            request_id, why = note.removeprefix("Left out ").split(", which does not validate: ")
            found[request_id] = why
    return found


MEAL_TIMES = [("08:00", "09:00"), ("12:00", "13:00"), ("17:30", "18:30"), ("10:30", "10:45")]


def blocks_with_meals(count):
    """Three clinic blocks plus `count` meal blocks."""
    blocks = {
        "clinic_1": ("09:15", "10:30", ("all_clinics",)),
        "clinic_2": ("10:45", "12:00", ("all_clinics",)),
        "clinic_3": ("14:00", "15:15", ("all_clinics",)),
    }
    for i, (start, end) in enumerate(MEAL_TIMES[:count]):
        blocks[f"meal_{i}"] = (start, end, ("meals",))
    return blocks


THREE_BREAKS = request(
    "breaks",
    "REQUEST EACH staff DO 'break' FOR EXACTLY 30m DURING ANY 3 blocks",
    Priority.MUST_HAPPEN,
)


@pytest.mark.parametrize("meals", [3, 4])
def test_avoid_is_one_small_request_per_person_and_block(meals):
    avoid = request(
        "at-meals",
        "REQUEST EACH staff NOT DO 'break' DURING EACH {blocks - blocks.meals}",
        Priority.HIGH,
        2,
    )
    ds = dataset(
        [staff("Sarah")], [], requests=[THREE_BREAKS, avoid], blocks=blocks_with_meals(meals)
    )
    placed = sorted(a.block for a in run(ds).assignments)
    assert len(placed) == 3 and all(b.startswith("meal") for b in placed)


def test_a_block_overlapping_two_clinics_does_not_stop_anyone_working_both():
    """Overlap is not transitive: rest hour meets both clinics, which do not meet each other."""
    blocks = {
        "clinic_1": ("09:15", "10:30", ("all_clinics",)),
        "rest_hour": ("10:00", "11:00", ()),
        "clinic_2": ("10:45", "12:00", ("all_clinics",)),
    }
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY, RIFLERY],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Archery 1 & 2", ["clinic_2"])],
        blocks=blocks,
    )
    result = run(ds)
    assert result.feasible and not result.unsatisfied
    assert sorted(a.block for a in where(result, staff="dylan")) == ["clinic_1", "clinic_2"]


def test_a_block_on_another_kind_of_day_never_clashes():
    """pack_out belongs to changeover days, so it cannot stop work on a regular day."""
    blocks = {
        "clinic_1": ("09:15", "10:30", ("all_clinics",)),
        "pack_out": ("09:15", "11:00", ()),
        "clinic_2": ("10:45", "12:00", ("all_clinics",)),
    }
    ds = dataset(
        [staff("Dylan", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"]), ("Archery 1 & 2", ["clinic_2"])],
        blocks=blocks,
    )
    ds = replace(
        ds,
        blocks={
            **ds.blocks,
            "pack_out": replace(ds.blocks["pack_out"], day_types=frozenset({"changeover"})),
        },
    )
    result = run(ds)
    assert result.feasible and not result.unsatisfied


# -- FREE, BUSY and priorities --------------------------------------------------------------


def test_free_requests_outrank_a_lower_tier_task():
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request(
                "playstation",
                "REQUEST EACH staff FREE DURING blocks.playstation",
                Priority.HIGH,
            ),
            request(
                "setup", "REQUEST staff.dylan DO 'setup' DURING blocks.playstation", Priority.MEDIUM
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
        requests=[request("busy", "REQUEST staff.sarah BUSY DURING blocks.clinic_1")],
    )
    assert where(run(ds), activity="archery_1_2")[0].staff == "sarah"
    rests = {TARGET: {"sarah": frozenset({"clinic_1"})}}
    resting = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Sarah", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request("busy", "REQUEST staff.sarah BUSY DURING blocks.clinic_1"),
            request("free", "REQUEST staff.sarah FREE DURING blocks.clinic_1"),
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
                "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING blocks.clinic_1",
                Priority.MEDIUM,
                1,
            ),
            request(
                "likes-riflery",
                "REQUEST staff.dylan DO activities.clinics.riflery DURING blocks.clinic_1",
                Priority.MEDIUM,
                2,
            ),
        ],
    )
    assert where(run(ds), staff="dylan")[0].activity == "riflery"


# -- amounts, mappings and past dates --------------------------------------------------------

PREFERENCE = (
    "PREFER EACH s IN staff DO EACH c IN activities.clinics MAXIMIZE mappings.preference(s, c)"
)
VARIETY = "PREFER EACH staff DO EACH activities.clinics DURING AT_MOST 1 blocks ON ANY {dates.target - 6d .. dates.target}"


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
        mappings=preference({("Dylan", "Archery 1 & 2"): 5, ("Dylan", "Candle Making"): 3}),
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
        mappings=preference(
            {("Dylan", "Archery 1 & 2"): 5, ("Dylan", "Candle Making"): 1}, default=1
        ),
        requests=[request("dislike", PREFERENCE.replace("MAXIMIZE", "MINIMIZE"), Priority.MEDIUM)],
    )
    assert where(run(ds), staff="dylan")[0].activity == "candle_making"


BUDDY = (
    "REQUEST mappings.buddy(staff.dylan) DO 'cover dylan' DURING blocks.playstation\n"
    "REQUEST mappings.buddy(staff.james) DO 'cover james' DURING blocks.playstation"
)
CABINS = {"counselor": ["Dylan", "James"], "director": ["David"]}


def cover(result, cabin: str) -> str:
    (assignment,) = where(result, activity=f"cover {cabin}")
    return assignment.staff


def test_a_buddy_covers_their_cabin_and_the_default_covers_one_without():
    members = [staff(n) for n in ("Dylan", "James", "David", "Alan", "Sarah")]
    ds = dataset(
        members,
        [],
        categories=CABINS,
        mappings=buddies({"Dylan": "Alan"}),
        requests=[request("buddies", BUDDY, Priority.MUST_HAPPEN)],
    )
    result = run(ds)
    assert cover(result, "dylan") == "alan"
    # James has no buddy written down, so it is anyone neither a counselor nor a director,
    # and Alan is already covering Dylan's cabin
    assert cover(result, "james") == "sarah"


def test_a_buddy_who_is_resting_is_covered_for_by_the_default():
    members = [staff(n) for n in ("Dylan", "James", "David", "Alan", "Sarah", "Lucy")]
    ds = dataset(
        members,
        [],
        categories=CABINS,
        mappings=buddies({"Dylan": "Alan", "James": "Sarah"}),
        requests=[request("buddies", BUDDY, Priority.MUST_HAPPEN)],
        rests={TARGET: {"alan": frozenset(BLOCKS)}},
    )
    result = run(ds)
    assert cover(result, "dylan") == "lucy"
    assert cover(result, "james") == "sarah"


def test_past_assignments_count_toward_at_most():
    yesterday = TARGET - timedelta(days=1)
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    variety = request("variety", VARIETY, Priority.MEDIUM)
    prefer_dylan = request(
        "dylan",
        "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING blocks.clinic_1",
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


def test_a_count_request_is_met_or_not():
    members = [
        staff("Dylan", archery_1_2=OK, candle_making=OK),
        staff("Randy", archery_1_2=OK, candle_making=OK),
    ]
    offerings = [("Archery 1 & 2", ["clinic_1"]), ("Candle Making", ["clinic_3"])]
    cap = request(
        "cap",
        "REQUEST EACH staff DO ANY activities.clinics DURING AT_MOST 1 blocks",
        Priority.MUST_HAPPEN,
    )
    both = request(
        "both",
        "REQUEST staff.dylan DO ANY activities.clinics DURING ALL {blocks.clinic_1 + blocks.clinic_3}",
    )
    ds = dataset(members, [ARCHERY, CANDLE], offerings=offerings, requests=[cap, both])
    result = run(ds)
    assert len({a.staff for a in result.assignments}) == 2
    assert ids(result.unsatisfied) == ["both"]
    exact = request(
        "two",
        "REQUEST staff.dylan DO ANY activities.clinics DURING ANY 2 blocks",
        Priority.MUST_HAPPEN,
    )
    result = run(dataset(members, [ARCHERY, CANDLE], offerings=offerings, requests=[exact]))
    assert {a.staff for a in result.assignments} == {"dylan"}


def test_a_counted_pattern_measures_clinics_without_starting_one():
    """Only a positive REQUEST … DO makes a clinic run, whatever a count would like."""
    members = [
        staff("Dylan", archery_1_2=OK, candle_making=OK),
        staff("Randy", archery_1_2=OK, candle_making=OK),
    ]
    offerings = [("Archery 1 & 2", ["clinic_1"]), ("Candle Making", ["clinic_3"])]
    exact = request(
        "two",
        "REQUEST staff.dylan DO ANY activities.clinics DURING ANY 2 blocks",
        Priority.MUST_HAPPEN,
    )
    result = run(dataset(members, [ARCHERY, CANDLE], offerings=offerings, requests=[exact]))
    assert result.feasible
    # the two offered clinics and nothing else, however many blocks the count could reach
    assert sorted((a.activity, a.block) for a in result.assignments) == [
        ("archery_1_2", "clinic_1"),
        ("candle_making", "clinic_3"),
    ]
    assert {a.staff for a in result.assignments} == {"dylan"}


def test_a_duration_amount_sums_lengths_and_past_dates_count():
    yesterday = TARGET - timedelta(days=1)
    text = "REQUEST staff.james DO 'dance practice' DURING ANY blocks.all_clinics ON ANY {dates.target - 1d .. dates.target} FOR AT_LEAST 2h"
    ds = dataset(
        [staff("James")],
        [],
        published=published(yesterday, ("James", "'dance practice'", None, "clinic_1", 75)),
        requests=[
            request("dance", text, Priority.MUST_HAPPEN),
            request("free", "REQUEST EACH staff FREE DURING EACH blocks", Priority.HIGH),
        ],
    )
    (today,) = where(run(ds), activity="dance practice")
    assert today.minutes == 45  # 75 done yesterday; the rest is part of one more block
    fresh = dataset([staff("James")], [], requests=[request("dance", text, Priority.MUST_HAPPEN)])
    assert sum(a.minutes for a in where(run(fresh), activity="dance practice")) >= 120


def test_consecutive_needs_adjacent_blocks():
    text = "REQUEST staff.james DO 'training' FOR AT_LEAST 1.5h DURING ANY CONSECUTIVE {{{blocks}}}"
    adjacent = dataset(
        [staff("James")],
        [],
        requests=[
            request(
                "t",
                text.format(blocks="blocks.clinic_2 + blocks.lunch + blocks.clinic_3"),
                Priority.MUST_HAPPEN,
            ),
            request("free", "REQUEST EACH staff FREE DURING EACH blocks", Priority.HIGH),
        ],
    )
    rows = sorted(where(run(adjacent), activity="training"), key=lambda a: a.start)
    assert [a.block for a in rows] in (["clinic_2", "lunch"], ["lunch", "clinic_3"])
    assert sum(a.minutes for a in rows) >= 90  # one of the two may be cut short
    apart = dataset(
        [staff("James")],
        [],
        requests=[request("t", text.format(blocks="blocks.clinic_1 + blocks.clinic_3"))],
    )
    assert ids(run(apart).unsatisfied) == ["t"]


def test_a_count_of_blocks_consecutive_chooses_blocks_next_to_each_other():
    """Clinic 2 and 3 are the two James is free to give, but lunch sits between them."""
    text = (
        "REQUEST ALL {{staff.james + staff.lucy}} DO 'training' DURING ANY 2 {}blocks.all_clinics"
    )
    keep_free = request(
        "free",
        "REQUEST staff.james FREE DURING EACH {blocks.clinic_1 + blocks.clinic_4}",
        Priority.HIGH,
    )
    members = [staff("James"), staff("Lucy")]

    def blocks_of(skedge):
        ds = dataset(members, [], requests=[request("t", skedge, Priority.MUST_HAPPEN), keep_free])
        result = run(ds)
        assert result.feasible
        rows = where(result, activity="training")
        chosen = {a.block for a in rows if a.staff == "james"}
        assert chosen == {a.block for a in rows if a.staff == "lucy"}  # together
        return chosen

    assert blocks_of(text.format("")) == {"clinic_2", "clinic_3"}
    in_a_row = blocks_of(text.format("CONSECUTIVE "))
    assert in_a_row in ({"clinic_1", "clinic_2"}, {"clinic_3", "clinic_4"})
    apart = dataset(
        members,
        [],
        requests=[
            request(
                "t",
                "REQUEST staff.james DO 'training' "
                "DURING ANY 2 CONSECUTIVE {blocks.clinic_2 + blocks.clinic_3}",
            )
        ],
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
                "REQUEST staff.dylan DO ANY activities.clinics DURING ALL {blocks.clinic_1 + blocks.clinic_2}",
                Priority.MEDIUM,
            ),
            request(
                "row",
                "REQUEST EACH staff DO ANY activities.clinics DURING AT_MOST 1 CONSECUTIVE blocks",
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert len({a.staff for a in result.assignments}) == 2
    assert ids(result.unsatisfied) == ["dylan"]


def test_prefer_at_most_consecutive_weighs_a_run():
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
                "REQUEST staff.dylan DO ANY activities.clinics DURING ALL {blocks.clinic_1 + blocks.clinic_2}",
                Priority.MEDIUM,
            ),
            request(
                "row",
                "PREFER EACH staff DO ANY activities.clinics DURING AT_MOST 1 CONSECUTIVE blocks",
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert result.feasible
    assert ids(result.unsatisfied) == ["dylan"]  # the preference outranks the request


def test_prefer_at_least_consecutive_rewards_a_run():
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
                "row",
                "PREFER staff.dylan DO ANY activities.clinics DURING AT_LEAST 2 CONSECUTIVE blocks",
                Priority.HIGH,
            ),
        ],
    )
    result = run(ds)
    assert {a.block for a in where(result, staff="dylan")} == {"clinic_1", "clinic_2"}


def test_two_requests_met_by_the_same_assignment_both_solve():
    """Each copy is hinted as met, and CP-SAT refuses a model hinting one variable twice."""
    ds = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request("free", "REQUEST staff.dylan FREE DURING blocks.playstation"),
            request("again", "REQUEST staff.dylan FREE DURING blocks.playstation"),
        ],
    )
    result = run(ds)
    assert result.feasible and not result.unsatisfied


def test_at_most_consecutive_caps_a_run_of_three_adjacent_blocks():
    """The run bound counts what a person can really hold, one assignment per block."""
    members = [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)]
    clinics = [clinic(f"C{i}", ("Archery 1 & 2", 1)) for i in range(3)]
    offerings = [(f"C{i}", [f"clinic_{i + 1}"]) for i in range(3)]
    cap = request(
        "row",
        "REQUEST EACH staff DO ANY activities.clinics DURING AT_MOST 2 CONSECUTIVE blocks",
        Priority.MUST_HAPPEN,
    )
    blocks = blocks_with_meals(0)
    # nothing but the cap keeps Dylan off all three
    greedy = request(
        "dylan",
        "REQUEST staff.dylan DO ANY activities.clinics DURING ANY 3 blocks",
        Priority.MEDIUM,
    )
    ds = dataset(members, clinics, offerings=offerings, requests=[cap, greedy], blocks=blocks)
    result = run(ds)
    assert result.feasible and ids(result.unsatisfied) == ["dylan"]
    assert len(where(result, staff="dylan")) <= 2  # the run is capped, so three is refused
    without_cap = dataset(members, clinics, offerings=offerings, requests=[greedy], blocks=blocks)
    assert len(where(run(without_cap), staff="dylan")) == 3
    loose = request(
        "row",
        "REQUEST EACH staff DO ANY activities.clinics DURING AT_MOST 3 CONSECUTIVE blocks",
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
                "balance",
                "PREFER EACH staff DO ANY activities.clinics DURING AT_MOST 1 blocks",
                Priority.MEDIUM,
            ),
            request(
                "dylan",
                "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING ALL {blocks.clinic_1 + blocks.clinic_3}",
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
    feud = "REQUEST staff.james NOT DO ANY activities.clinics WITH staff.paul DURING EACH blocks"
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
    assert result.feasible and requests_of(result.unsatisfied) == [
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
                "REQUEST staff.james NOT DO ANY activities.clinics WITH staff.paul",
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
                "REQUEST staff.james DO activities.clinics.craft_fairy DURING blocks.clinic_1 WITH staff.paul",
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
                "REQUEST staff.rob NOT DO ANY activities.clinics.ropes WITHOUT staff.vic",
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


@pytest.mark.parametrize(
    ("company", "partners", "done"),
    [
        ("AT_LEAST 1", ["sarah"], True),
        ("AT_LEAST 2", ["sarah"], False),
        ("AT_LEAST 2", ["sarah", "vic"], True),
        ("ALL", ["sarah", "vic"], False),
    ],
)
def test_without_counts_how_many_of_the_set_are_there(company, partners, done):
    rule = f"REQUEST staff.dylan NOT DO 'setup' WITHOUT {company} {{staff.sarah + staff.vic + staff.randy}}"
    setup = "REQUEST staff.{} DO 'setup' FOR EXACTLY 30m DURING blocks.clinic_1"
    ds = dataset(
        [staff("Dylan"), staff("Sarah"), staff("Vic"), staff("Randy")],
        [],
        requests=[
            request("rule", rule, Priority.MUST_HAPPEN),
            request("dylan", setup.format("dylan"), Priority.HIGH),
            *(request(p, setup.format(p), Priority.MUST_HAPPEN) for p in partners),
        ],
    )
    result = run(ds)
    assert result.feasible and ids(result.unsatisfied) == ([] if done else ["dylan"])


def test_with_on_a_quoted_task_means_the_same_start():
    together = (
        "prep:  REQUEST staff.dylan DO 'prep' FOR EXACTLY 30m DURING blocks.clinic_1\n"
        "setup: REQUEST staff.dylan DO 'setup' FOR EXACTLY 30m DURING blocks.clinic_1 WITH staff.sarah\n"
        "GAP prep TO setup AT_LEAST 0m"
    )
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request("dylan", together, Priority.MUST_HAPPEN),
            request(
                "sarah",
                "REQUEST staff.sarah DO 'setup' FOR EXACTLY 30m DURING blocks.clinic_1",
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
        "EACH s IN staff\n"
        "IF s BUSY DURING blocks.playstation ON {dates.target - 1d} THEN\n"
        "{ REQUEST s FREE DURING blocks.clinic_1 }"
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
        "UNLESS ANY staff.director FREE DURING blocks.clinic_1 THEN\n"
        "{ REQUEST ANY 1 staff.office DO 'front desk' DURING blocks.clinic_1 }"
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


def test_only_what_is_in_the_braces_depends_on_the_test():
    """Mail is asked for either way; the desk only when a director is busy, and Lisa free later."""
    text = (
        "IF ANY staff.director BUSY DURING blocks.clinic_1 THEN\n"
        "{\n"
        "    IF ANY staff.office FREE DURING blocks.clinic_3 THEN\n"
        "    {\n"
        "        REQUEST staff.lisa DO 'front desk' DURING blocks.clinic_1\n"
        "    }\n"
        "}\n"
        "REQUEST staff.lisa DO 'mail' DURING blocks.clinic_2"
    )
    members = [staff("David", archery_1_2=OK), staff("Lisa")]
    categories = {"director": ["David"], "office": ["Lisa"]}
    idle = run(dataset(members, [ARCHERY], categories=categories, requests=[request("t", text)]))
    assert where(idle, activity="mail") and not where(idle, activity="front desk")
    assert idle.unsatisfied == ()
    busy = run(
        dataset(
            members,
            [ARCHERY],
            offerings=[("Archery 1 & 2", ["clinic_1"])],
            categories=categories,
            requests=[request("t", text)],
        )
    )
    assert where(busy, activity="mail") and where(busy, activity="front desk")
    assert busy.unsatisfied == ()


def test_if_with_an_amount_over_a_run():
    text = (
        "EACH s IN staff\n"
        "IF s DO ANY activities.clinics DURING AT_LEAST 2 CONSECUTIVE blocks THEN\n"
        "{ REQUEST s FREE DURING blocks.clinic_3 }"
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


def test_and_or_join_conditions():
    members = [staff("David", archery_1_2=OK), staff("Lisa")]
    categories = {"director": ["David"], "office": ["Lisa"]}

    def desk(joined):
        text = (
            f"IF ANY staff.director FREE DURING blocks.clinic_1\n{joined} staff.lisa FREE DURING blocks.clinic_2 THEN\n"
            "{ REQUEST staff.lisa DO 'front desk' DURING blocks.clinic_1 }"
        )
        ds = dataset(members, [ARCHERY], categories=categories, requests=[request("desk", text)])
        return where(run(ds), activity="front desk")

    # Lisa is free in clinic 2 whatever happens, so OR holds and AND holds too.
    assert desk("AND") and desk("OR")
    busy = (
        "IF ANY staff.director BUSY DURING blocks.clinic_1\n{} staff.lisa FREE DURING blocks.clinic_2 THEN\n"
        "{{ REQUEST staff.lisa DO 'front desk' DURING blocks.clinic_1 }}"
    )
    for joined, expected in (("AND", False), ("OR", True)):
        ds = dataset(
            members,
            [ARCHERY],
            categories=categories,
            requests=[request("desk", busy.format(joined))],
        )
        assert bool(where(run(ds), activity="front desk")) is expected


# -- the time horizon ------------------------------------------------------------------------

MAINTENANCE = "REQUEST staff.dylan DO 'archery maintenance' DURING ANY 1 blocks ON ANY 1 {2026-09-16 .. 2026-09-17}"
KEEP_FREE = request("free", "REQUEST EACH staff FREE DURING EACH blocks", Priority.HIGH, 0.5)


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
    text = (
        "REQUEST staff.dylan DO 'inventory' DURING ANY 2 blocks ON ANY {2026-09-16 .. 2026-09-17}"
    )
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


# -- EXCLUDE ---------------------------------------------------------------------------------

OFFSITE = "EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks"
BREAKS = "REQUEST EACH staff DO 'break' FOR EXACTLY 30m DURING ANY 1 blocks"


def with_breaks(*exclusions):
    """A day with a legal break everybody must get, and whoever is excluded from it."""
    return dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        categories={"all": ["Dylan", "Sarah"]},
        requests=[
            request("breaks", BREAKS, Priority.MUST_HAPPEN),
            *[
                request(f"away-{i}", text, Priority.MUST_HAPPEN)
                for i, text in enumerate(exclusions)
            ],
        ],
    )


def test_a_day_off_does_not_stop_the_day_being_solved():
    """The legal breaks stay MUST_HAPPEN and are asked of the staff who are at camp."""
    result = run(with_breaks(OFFSITE))
    assert result.feasible and result.conflicts == ()
    assert [a.staff for a in where(result, activity="break")] == ["sarah"]
    assert where(result, staff="dylan") == []  # nothing at all is assigned to him


def test_nothing_may_be_put_in_a_block_somebody_is_excluded_from():
    """A clinic cannot use them and no request can reach them there."""
    ds = with_breaks("EXCLUDE staff.dylan DO 'offsite' DURING blocks.clinic_1")
    ds = replace(
        ds,
        requests=(
            *ds.requests,
            request("pin", "REQUEST staff.dylan DO 'inventory' DURING blocks.clinic_1"),
        ),
    )
    result = run(ds)
    assert result.feasible
    assert where(result, staff="dylan", block="clinic_1") == []
    assert ids(result.unsatisfied) == ["pin"]  # asked for anyway, and not met


def test_a_morning_off_still_owes_them_their_afternoon_break():
    """Somebody back after lunch is at camp, so the day's MUST_HAPPEN rules still reach them."""
    morning = "EXCLUDE staff.dylan DO 'dentist' DURING ALL {blocks.clinic_1 + blocks.clinic_2}"
    result = run(with_breaks(morning))
    assert result.feasible
    (dylan,) = where(result, staff="dylan", activity="break")
    assert dylan.block not in ("clinic_1", "clinic_2")


def test_an_exclusion_is_neither_unsatisfied_nor_inactive():
    """It is not a request the solver weighs; it is the day it weighs everything else in."""
    result = run(with_breaks(OFFSITE))
    assert ids(result.unsatisfied) == [] and ids(result.inactive) == []
    assert ids(result.deferred) == []


def test_past_and_future_requests_are_inactive():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request(
                "past", "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON {dates.target - 1d}"
            ),
            request("future", "REQUEST staff.dylan NOT DO 'x' ON {dates.target + 1d}"),
            request("empty", "REQUEST EACH {staff - staff.dylan} DO 'x' DURING blocks.clinic_1"),
            request("today", "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1"),
        ],
    )
    result = run(ds)
    assert ids(result.inactive) == ["past", "future", "empty"]
    assert len(where(result, activity="x")) == 1


def test_all_of_dates_are_enforced_every_day():
    yesterday = TARGET - timedelta(days=1)
    text = "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON ALL {dates.target - 1d .. dates.target}"
    done = dataset(
        [staff("Dylan")],
        [],
        published=published(yesterday, ("Dylan", "'x'", None, "clinic_1")),
        requests=[request("x", text)],
    )
    assert run(done).unsatisfied == ()
    missed = dataset([staff("Dylan")], [], requests=[request("x", text)])
    assert ids(run(missed).unsatisfied) == ["x"]


def test_an_invalid_request_is_left_out_of_the_solve_and_said_so():
    bad = "REQUEST staff.dylan DO 'x' DURING AT_LEAST 2 blocks"
    good = "REQUEST staff.dylan DO 'y' DURING blocks.clinic_1"
    ds = dataset([staff("Dylan")], [], requests=[request("bad", bad), request("good", good)])
    result = run(ds)
    assert "bad" in left_out(result) and "to pick 2, write ANY 2" in left_out(result)["bad"]
    assert result.feasible and where(result, activity="y")
    assert "bad" not in ids(result.inactive)  # a note says why, not "does nothing today"


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


# -- one block, several statements -----------------------------------------------------------


BOTH = [staff("Dylan", candle_making=OK), staff("Mogee", candle_making=OK)]
DYLAN_IN_CLINIC_2 = (
    "PREFER staff.dylan DO activities.clinics.candle_making DURING AT_LEAST 1 blocks.clinic_2"
)


def test_one_request_may_require_and_prefer_at_once():
    """A declaration can say what must happen and what would be better, in one block."""
    ds = dataset(
        BOTH,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "candle-plan",
                "REQUEST staff.mogee DO activities.clinics.candle_making DURING blocks.clinic_1\n"
                + DYLAN_IN_CLINIC_2,
                Priority.MEDIUM,
            )
        ],
    )
    result = run(ds)
    assert result.feasible and not result.unsatisfied
    assert where(result, block="clinic_1")[0].staff == "mogee"  # the requirement
    assert where(result, block="clinic_2")[0].staff == "dylan"  # the preference


def test_a_mixed_request_is_reported_on_its_requirements():
    """The report is about the REQUEST statements; the PREFER statements only pull the score."""
    ds = dataset(
        BOTH,
        [ARCHERY, CANDLE],
        offerings=[("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "impossible",
                "REQUEST staff.mogee DO activities.clinics.archery_1_2 DURING blocks.clinic_1\n"
                + DYLAN_IN_CLINIC_2,
                Priority.MEDIUM,
            )
        ],
    )
    result = run(ds)
    assert result.feasible
    assert ids(result.unsatisfied) == ["impossible"]  # named once, for its requirement
    assert where(result, block="clinic_2")[0].staff == "dylan"  # its preference still counted


def test_several_preferences_may_share_one_request():
    ds = dataset(
        BOTH,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"]), ("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "who-goes-where",
                "PREFER staff.dylan DO activities.clinics.candle_making DURING AT_LEAST 1 blocks.clinic_1\n"
                "PREFER staff.mogee DO activities.clinics.candle_making DURING AT_LEAST 1 blocks.clinic_2",
            )
        ],
    )
    result = run(ds)
    assert result.feasible
    assert where(result, block="clinic_1")[0].staff == "dylan"
    assert where(result, block="clinic_2")[0].staff == "mogee"


def test_each_of_still_expands_the_whole_block():
    """A binding is the declaration's, so a requirement beside it is made once per item."""
    ds = dataset(
        BOTH,
        [CANDLE],
        offerings=[("Candle Making", ["clinic_1"]), ("Candle Making", ["clinic_2"])],
        requests=[
            request(
                "each-one",
                "EACH s IN staff\n"
                "REQUEST s DO activities.clinics.candle_making DURING ANY 1 blocks.all_clinics\n"
                "PREFER s DO activities.clinics.candle_making DURING AT_MOST 1 blocks",
                Priority.MEDIUM,
            )
        ],
    )
    result = run(ds)
    assert result.feasible
    assert ids(result.unsatisfied) == []
    assert {a.staff for a in result.assignments} == {"dylan", "mogee"}


def test_a_preference_cannot_ride_along_on_a_hard_request():
    """There is no tier above the hard one for a preference to be weighed in."""
    ds = dataset(
        BOTH,
        [CANDLE],
        requests=[
            request(
                "both",
                "REQUEST staff.dylan DO activities.clinics.candle_making DURING blocks.clinic_1\n"
                "PREFER staff.mogee DO activities.clinics.candle_making DURING AT_MOST 1 blocks",
                priority=Priority.MUST_HAPPEN,
            )
        ],
    )
    assert "PREFER needs a priority it can be weighed at" in left_out(run(ds))["both"]


def test_a_position_may_name_one_person():
    """A cabin act asks for Dylan by name: nobody else can hold that position."""
    act = cabin_act("M1", "Lake Day", ("Dylan", {"dylan"}))
    ds = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Rob", archery_1_2=OK)],
        [ARCHERY, act],
        requests=[request("act", "REQUEST activities.cabin_acts.m1 DURING blocks.clinic_1")],
    )
    result = run(ds)
    assert result.feasible
    assert [a.staff for a in result.assignments if a.activity == act.id] == ["dylan"]


def test_a_position_may_name_a_category():
    """Anyone in the category will do, but nobody outside it."""
    act = cabin_act("M2", "Fort Building", ("VLs", {"rob", "vic"}))
    ds = dataset(
        [staff("Dylan", archery_1_2=OK), staff("Rob", archery_1_2=OK)],
        [ARCHERY, act],
        requests=[request("act", "REQUEST activities.cabin_acts.m2 DURING blocks.clinic_1")],
    )
    result = run(ds)
    assert result.feasible
    assert [a.staff for a in result.assignments if a.activity == act.id] == ["rob"]


def test_a_target_session_request_is_skipped_on_a_date_in_no_session(dataset):
    """It is right on a session's dates, so the day is solved without it rather than not at all."""
    camp = family_camp(dataset)
    request = Request(
        "camp-1",
        "",
        "REQUEST staff.dylan DO 'x' DURING ANY 1 blocks ON dates.session_target",
        Priority.HIGH,
    )
    result = solve(replace(camp, requests=(request,)))
    assert result.feasible and ids(result.inactive) == ["camp-1"]


def test_not_all_of_forbids_them_together_and_allows_either():
    """`NOT DO … DURING ALL {a + b}` is not both; either one on its own is fine."""
    forbid = request(
        "not-both",
        "REQUEST staff.lisa NOT DO 'desk' DURING ALL {blocks.clinic_1 + blocks.clinic_2}",
        Priority.MUST_HAPPEN,
    )

    def desk(*blocks):
        asks = [
            request(
                f"desk-{b}", f"REQUEST staff.lisa DO 'desk' DURING blocks.{b}", Priority.MUST_HAPPEN
            )
            for b in blocks
        ]
        return run(dataset([staff("Lisa")], [], requests=[forbid, *asks]))

    one = desk("clinic_1")
    assert one.feasible and [a.block for a in where(one, activity="desk")] == ["clinic_1"]
    both = desk("clinic_1", "clinic_2")
    assert not both.feasible and "not-both" in both.conflicts


# -- copies resolved beforehand ---------------------------------------------------------------


def _known(ds):
    from puppet_strings.skedge.validate import validate_request

    return Resolutions(ds, {r.id: (r, validate_request(r, ds)) for r in ds.requests})


def test_a_solve_uses_copies_resolved_beforehand(monkeypatch):
    import puppet_strings.solver.solve as solving

    ds = dataset([staff("Dylan")], [], requests=[request("x", "REQUEST staff.dylan DO 'x'")])
    known = _known(ds)
    checked = []
    real = solving.validate_request
    monkeypatch.setattr(
        solving, "validate_request", lambda r, d: checked.append(r.id) or real(r, d)
    )
    assert where(solve(ds, CONFIG, known=known), activity="x")
    assert checked == []


def test_a_request_edited_since_or_a_day_changed_since_is_resolved_again(monkeypatch):
    import puppet_strings.solver.solve as solving

    ds = dataset([staff("Dylan")], [], requests=[request("x", "REQUEST staff.dylan DO 'x'")])
    known = _known(ds)
    edited = replace(ds, requests=(request("x", "REQUEST staff.dylan DO 'y'"),))
    checked = []
    real = solving.validate_request
    monkeypatch.setattr(
        solving, "validate_request", lambda r, d: checked.append(r.id) or real(r, d)
    )
    assert where(solve(edited, CONFIG, known=known), activity="y")
    away = replace(ds, staff_categories={**ds.staff_categories, "all": frozenset()})
    solve(away, CONFIG, known=known)
    assert checked == ["x", "x"]


def test_an_invalid_request_is_still_left_out_with_copies_resolved_beforehand():
    bad = request("bad", "REQUEST staff.dylan DO 'x' DURING AT_LEAST 2 blocks")
    ds = dataset([staff("Dylan")], [], requests=[bad])
    known = Resolutions(ds, {"bad": (bad, ())})  # what the window keeps for an invalid one
    assert "to pick 2, write ANY 2" in left_out(solve(ds, CONFIG, known=known))["bad"]


def test_with_in_a_role_counts_the_partner_only_in_that_role():
    """Dylan works the zip line only if Sarah is first on it, not merely on it."""
    both = dict(gravity_zip_line_1st=OK, gravity_zip_line_2nd=OK)
    members = [staff("Dylan", **both), staff("Sarah", **both), staff("Vic", **both)]
    sarah_second = PIN.format(who="sarah", what="gravity_zip_line", role="second", block="clinic_1")
    wish = "REQUEST staff.dylan DO activities.clinics.gravity_zip_line DURING blocks.clinic_1"

    def unmet(rule):
        ds = dataset(
            members,
            [ZIP],
            requests=[
                request("rule", rule, Priority.MUST_HAPPEN),
                request("sarah", sarah_second, Priority.MUST_HAPPEN),
                request("dylan", wish),
            ],
        )
        result = run(ds)
        assert result.feasible
        return ids(result.unsatisfied)

    rule = "REQUEST staff.dylan NOT DO activities.clinics.gravity_zip_line WITHOUT staff.sarah"
    assert unmet(rule) == []  # Sarah is on it, second
    assert unmet(rule + " AS_ROLE roles.first") == ["dylan"]  # but not first
    pair = (
        "REQUEST staff.dylan DO activities.clinics.gravity_zip_line AS_ROLE roles.second "
        "WITH staff.sarah AS_ROLE roles.first DURING blocks.clinic_1"
    )
    ds = dataset(members, [ZIP], requests=[request("pair", pair, Priority.MUST_HAPPEN)])
    rows = {(a.staff, a.role) for a in run(ds).assignments if a.activity == "gravity_zip_line"}
    assert rows == {("dylan", "second"), ("sarah", "first")}
