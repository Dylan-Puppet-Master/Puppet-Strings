from datetime import date, time

import pytest

from puppet_strings.model import Offering, SkillStatus
from puppet_strings.names import normalize
from puppet_strings.sheets.blocks import parse_blocks
from puppet_strings.sheets.calendar import parse_calendar
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import assignment_rows, parse_published
from puppet_strings.sheets.requests import parse_requests, request_rows
from puppet_strings.sheets.skills import (
    ClinicPositions,
    known_skills,
    parse_position_skills,
    parse_skills,
    trainers,
)
from puppet_strings.sheets.source import LoadError, parse_time

_KNOWN = {"canoe": "Canoe"}  # skills the Skills tab of a hand-built table has columns for


def _known(source):
    return known_skills(source.read("skills", "Skills"))


def _positions(clinic: str, *skills: str | None) -> dict[str, ClinicPositions]:
    """A Positions tab of one row, padded with blank cells."""
    padded = tuple(skills) + (None,) * (3 - len(skills))
    return {normalize(clinic): ClinicPositions(clinic, padded)}


def test_skills_statuses(source):
    staff, warnings = parse_skills(source.read("skills", "Skills"))
    assert staff["alan"].skills["canopy_tour_1st"] is SkillStatus.CHECKED_OFF
    assert staff["alan"].skills["gravity_zip_line_1st"] is SkillStatus.CHECKED_OFF
    assert staff["audrey"].skills["candle_making"] is SkillStatus.TRAINER
    assert staff["cam_vl"].skills["ceramics_wheel"] is SkillStatus.NEEDS_SCAFFOLD
    assert staff["cam_vl"].skills["candle_making"] is SkillStatus.NEEDS_SCAFFOLD
    assert staff["paul"].skills["candle_making"] is SkillStatus.NEEDS_SHADOW
    assert staff["brian"].skills["riflery"] is SkillStatus.CHECKED_OFF
    assert staff["dylan"].skills["riflery"] is SkillStatus.NONE
    assert staff["alesa"].skills["lifeguard"] is SkillStatus.CHECKED_OFF
    assert "canopy_tour" not in staff["alan"].skills  # date columns are skipped
    assert staff["randy"].ral == 5
    assert staff["brian"].ral == 3
    assert warnings == ["Skills: Tyson / Low Ropes: unknown status 'Yes' ignored"]
    assert trainers(staff) == {"audrey", "alexis"}


def test_skill_status_properties():
    assert SkillStatus.TRAINER.eligible and SkillStatus.TRAINER.can_scaffold
    assert SkillStatus.CHECKED_OFF.eligible and not SkillStatus.CHECKED_OFF.can_scaffold
    assert SkillStatus.NEEDS_SCAFFOLD.trainee_role == "scaffolded"
    assert SkillStatus.NEEDS_SHADOW.trainee_role == "shadow"
    assert SkillStatus.NONE.trainee_role == "shadow"


def test_position_skills(source):
    skills = parse_position_skills(source.read("skills", "Positions"), _known(source))
    assert skills["gravity_zip_line"].skills == (
        "gravity_zip_line_1st",
        "gravity_zip_line_2nd",
        None,
    )
    assert skills["low_ropes"].skills == ("low_ropes", "any", None)
    # the Skills column is "Candle making" and the Positions cell "Candle Making"
    assert skills["candle_making"].skills[0] == "candle_making"


def test_position_skills_reject_a_skill_with_no_column(source):
    table = [
        ["Clinic_Name", "1st", "2nd", "3rd"],
        ["Canoe 1 & 2", "Kayaking", "", ""],
    ]
    with pytest.raises(LoadError, match="no column for these"):
        parse_position_skills(table, {"canoe": "Canoe"})


def test_clinics(source):
    known = _known(source)
    skills = parse_position_skills(source.read("skills", "Positions"), known)
    activities = parse_clinics(source.read("clinic_data", "Clinics"), skills, known)
    zip_line = activities["gravity_zip_line"]
    assert [p.role for p in zip_line.positions] == ["first", "second"]
    assert [p.ral for p in zip_line.positions] == [5, 3]
    assert zip_line.positions[1].skill == "gravity_zip_line_2nd"
    assert activities["blacksmithing_dbl"].double
    canoe = activities["canoe_1_2"]
    assert [(p.role, p.skill, p.ral) for p in canoe.positions] == [
        ("first", "canoe", 5),
        ("lifeguard", "lifeguard", 5),
    ]
    assert [p.role for p in activities["secret_pool"].positions] == ["first", "lifeguard"]
    assert activities["craft_fairy"].positions[0].skill is None
    assert activities["craft_fairy"].slots == 0
    assert activities["salsa"].positions[0].skill is None
    assert activities["salsa"].category == "performance"


def test_clinics_reject_wrong_ral_length():
    table = [
        ["Clinic_Name", "Slots", "Staff_Required", "RAL_Required", "Category"],
        ["Canoe 1", "8", "2", "5", "Water"],
    ]
    with pytest.raises(LoadError, match="must be 2 digits"):
        parse_clinics(table, _positions("Canoe 1", "canoe"), _KNOWN)


def test_clinics_reject_a_blank_position_cell():
    table = [
        ["Clinic_Name", "Slots", "Staff_Required", "RAL_Required", "Category"],
        ["Canoe 1", "8", "2", "55", "Water"],
    ]
    with pytest.raises(LoadError, match="second position's cell is blank"):
        parse_clinics(table, _positions("Canoe 1", "canoe"), _KNOWN)


def test_clinics_reject_a_clinic_missing_from_positions():
    table = [
        ["Clinic_Name", "Slots", "Staff_Required", "RAL_Required", "Category"],
        ["Canoe 1", "8", "1", "5", "Water"],
    ]
    with pytest.raises(LoadError, match="no row on the Positions tab"):
        parse_clinics(table, {}, _KNOWN)


def test_clinics_reject_a_positions_row_naming_no_clinic():
    table = [
        ["Clinic_Name", "Slots", "Staff_Required", "RAL_Required", "Category"],
        ["Canoe 1", "8", "1", "5", "Water"],
    ]
    positions = {**_positions("Canoe 1", "canoe"), **_positions("Canoe 2", "canoe")}
    with pytest.raises(LoadError, match="a Positions row for no clinic"):
        parse_clinics(table, positions, _KNOWN)


def test_offerings(dataset):
    offered = {o.activity: o.blocks for o in dataset.offerings}
    assert offered["pole_course_explore_level_1_2_dbl"] == ("clinic_1", "clinic_2")
    assert offered["blacksmithing_dbl"] == ("clinic_1", "clinic_2")
    assert Offering("candle_making", ("clinic_2",)) in dataset.offerings
    assert Offering("candle_making", ("clinic_3",)) in dataset.offerings
    assert sum(1 for o in dataset.offerings if o.activity == "craft_fairy") == 4
    assert Offering("riflery", ("clinic_3",)) in dataset.offerings
    assert not any(o.activity == "riflery" and o.blocks == ("clinic_1",) for o in dataset.offerings)
    assert "Offerings: tab says WEDNESDAY" not in " ".join(dataset.warnings)


def test_offerings_weekday_warning_and_unknown_clinic(dataset):
    table = [["THURSDAY"], ["Clinic 1"], ["ARTS"], ["Candle Making"], ["Basket Weaving"]]
    with pytest.raises(LoadError, match="'Basket Weaving' under clinic_1"):
        parse_offerings(table, dataset.activities, set(dataset.blocks), "Wednesday")
    _, warnings = parse_offerings(table[:4], dataset.activities, set(dataset.blocks), "Wednesday")
    assert warnings == ["Offerings: tab says THURSDAY but the target date is a Wednesday"]


def test_offerings_warn_about_a_heading_that_is_no_block(dataset):
    table = [
        ["WEDNESDAY", "", ""],
        ["Clinic 1", "slots", "Play Station"],
        ["Candle Making", "6", "Craft Fairy"],
    ]
    offerings, warnings = parse_offerings(
        table, dataset.activities, set(dataset.blocks), "Wednesday"
    )
    assert offerings == (Offering("candle_making", ("clinic_1",)),)
    assert warnings == [
        "Offerings: row 2 heading 'Play Station' is no block on the Blocks sheet, "
        "so nothing under it was offered"
    ]


def test_offerings_reject_lone_double(dataset):
    table = [["WEDNESDAY"], ["Clinic 1", "Clinic 2"], ["Blacksmithing (DBL)", ""]]
    with pytest.raises(LoadError, match="only in clinic_1"):
        parse_offerings(table, dataset.activities, set(dataset.blocks), "Wednesday")


def test_blocks(source):
    blocks = parse_blocks(source.read("config", "Blocks"))
    assert blocks["clinic_1"].start == time(9, 15)
    assert blocks["clinic_1"].minutes == 75
    assert blocks["lunch"].categories == {"all", "meals"}
    assert blocks["lunch"].day_types == {"regular", "changeover"}
    assert blocks["clinic_1"].gap_to(blocks["clinic_4"]) == 315
    assert not blocks["clinic_1"].overlaps(blocks["clinic_2"])
    assert blocks["lunch"].overlaps(blocks["lunch"])
    assert blocks["pack_out"].overlaps(blocks["clinic_1"])


def test_requests_round_trip(source):
    table = source.read("config", "Requests")
    requests = parse_requests(table)
    assert requests[0].id == "counselor-hours"
    assert requests[0].weight == 1.0
    assert requests[3].weight == 0.5
    assert requests[0].created == date(2026, 9, 1)
    assert requests[0].tags == ("legal", "counselors")
    assert requests[2].tags == ()
    assert requests[-1].tags == ("generated",)
    assert requests[0].groups == ("Special daily requests",)
    assert requests[-1].groups == ("Clinic requests",)
    assert requests[0].requester == "lucy"
    assert requests[1].requester == ""
    assert parse_requests(request_rows(requests)) == requests


def test_requests_read_a_sheet_written_before_groups_existed():
    """The three newest columns are optional, so an older Requests tab still loads."""
    table = [
        ["id", "description", "skedge", "priority", "weight", "created"],
        ["x", "", "REQUEST staff.dylan FREE DURING block.clinic_1", "HIGH", "2", ""],
    ]
    (request,) = parse_requests(table)
    assert request.tags == () and request.groups == () and request.requester == ""


def test_a_requester_is_normalized_like_any_other_name():
    table = [
        ["id", "description", "skedge", "priority", "weight", "requester", "created"],
        ["x", "", "REQUEST staff.dylan FREE DURING block.clinic_1", "HIGH", "", "Mary Kate", ""],
    ]
    assert parse_requests(table)[0].requester == "mary_kate"


def test_requests_reject_weight_on_hard():
    table = [
        ["id", "description", "skedge", "priority", "weight", "created"],
        ["x", "", "REQUEST staff.dylan FREE DURING block.clinic_1", "MUST_HAPPEN", "2", ""],
    ]
    with pytest.raises(LoadError, match="not allowed with MUST_HAPPEN"):
        parse_requests(table)


def test_metrics(dataset):
    preference = dataset.metrics["preference"]
    assert preference.keys == ("staff", "activity")
    assert preference.normalized(("dylan", "archery_1_2")) == 1.0
    assert preference.normalized(("dylan", "candle_making")) == 0.5
    assert preference.default == 3 and preference.missing == 3
    assert preference.normalized(("dylan", "riflery")) == 0.5  # no row, so the default


def test_metric_default_column(source):
    from puppet_strings.sheets.metrics import parse_metric_index

    table = source.read("config", "Metrics")
    header, row = table[0], table[1]
    blank = [header, [c if header[i] != "default" else "" for i, c in enumerate(row)]]
    (metric,) = parse_metric_index(blank)
    assert metric.default == 1 and metric.normalized(("anyone", "anything")) == 0.0
    outside = [header, [c if header[i] != "default" else "9" for i, c in enumerate(row)]]
    with pytest.raises(LoadError, match="default 9.0 is outside 1.0..5.0"):
        parse_metric_index(outside)
    without_column = [[c for c in header if c != "default"], row[: len(header) - 1]]
    (metric,) = parse_metric_index(without_column)
    assert metric.default == 1


def test_published_round_trip(dataset, source):
    yesterday = date(2026, 9, 15)
    assignments = dataset.published[yesterday]
    assert len(assignments) == 5
    hour = next(a for a in assignments if a.activity == "counselor hour")
    assert hour.staff == "dylan" and hour.role is None and hour.block == "clinic_2"
    assert (hour.start.strftime("%H:%M"), hour.minutes) == ("10:45", 60)
    rows = assignment_rows(assignments, dataset.staff, dataset.activities)
    assert set(map(tuple, rows[1:])) == set(map(tuple, source.read("published", "2026-09-15")[1:]))
    assert set(parse_published(rows, yesterday, dataset.staff, dataset.activities)) == set(
        assignments
    )


CALENDAR = [
    ["date", "session", "week", "day_type"],
    ["2026-09-13", "1", "1", "regular"],
    ["2026-09-20", "1", "2", "changeover"],
    ["2026-09-27", "2", "1", "regular"],
]


def test_calendar_numbers_sessions_and_weeks():
    days = parse_calendar(CALENDAR)
    first = days[date(2026, 9, 13)]
    assert (first.session, first.week, first.day_type) == (1, 1, "regular")
    assert days[date(2026, 9, 27)].session == 2


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["2026-10-04", "one", "1", "regular"], "expected a whole number"),
        (["2026-10-04", "0", "1", "regular"], "session must be between 1 and 20"),
        (["2026-10-04", "2", "21", "regular"], "week must be between 1 and 20"),
        (["2026-09-13", "1", "1", "regular"], "appears twice"),
        (["2026-10-04", "2", "3", "regular"], "session 2 has a week 2 with no days"),
    ],
)
def test_calendar_rejects_numbers_it_cannot_name(row, message):
    with pytest.raises(LoadError, match=message):
        parse_calendar([*CALENDAR, row])


def test_dataset(dataset):
    assert dataset.staff_categories["counselor"] == {"dylan", "james", "paul"}
    assert dataset.staff_categories["village_hero"] == {"audrey", "mogee"}
    assert dataset.staff_categories["clinic_trainers"] == {"audrey", "alexis"}
    assert "etc" not in dataset.staff_categories
    assert len(dataset.staff_categories["all"]) == 21
    assert dataset.activity_categories["ropes"] == {
        "gravity_zip_line",
        "pole_course_explore_level_1_2_dbl",
        "canopy_tour_dbl",
        "lvl_2_on_ground",
    }
    assert dataset.block_categories["any_clinic"] == {
        "clinic_1",
        "clinic_2",
        "clinic_3",
        "clinic_4",
    }
    assert dataset.session_dates[0] == date(2026, 9, 13)
    assert len(dataset.session_dates) == 14  # a two-week session
    assert dataset.session == 1
    assert list(dataset.sessions) == [1, 2]
    assert list(dataset.weeks(1)) == [1, 2]
    assert dataset.weeks(1)[2][0] == date(2026, 9, 20)
    assert dataset.week_dates == dataset.session_dates[:7]  # the target is in week 1
    assert [b.id for b in dataset.blocks_on(dataset.target)][:3] == [
        "breakfast",
        "clinic_1",
        "clinic_2",
    ]
    assert [b.id for b in dataset.blocks_on(date(2026, 9, 19))] == [
        "breakfast",
        "lunch",
        "playstation",
        "pack_out",
    ]
    assert set(dataset.published) == {date(2026, 9, 14), date(2026, 9, 15)}


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("8:30", time(8, 30)),
        ("08:30", time(8, 30)),
        (" 8:30 ", time(8, 30)),
        ("8:30 AM", time(8, 30)),
        ("8:30AM", time(8, 30)),
        ("5:45 pm", time(17, 45)),
        ("17:45", time(17, 45)),
        ("08:30:00", time(8, 30)),
        ("12:00", time(12, 0)),
    ],
)
def test_a_time_may_be_written_any_ordinary_way(written, expected):
    assert parse_time(written, "Blocks") == expected


def test_a_time_that_is_not_a_time_says_so():
    with pytest.raises(LoadError, match="must look like 8:30, 08:30 or 8:30 AM"):
        parse_time("half eight", "Blocks")


def test_blocks_accept_a_missing_leading_zero(source):
    table = [row[:] for row in source.read("config", "Blocks")]
    times = {row[0]: (row[1], row[2]) for row in table[1:]}
    for row in table[1:]:
        row[1] = row[1].lstrip("0")  # 09:15 as a person would type it
    blocks = parse_blocks(table)
    assert blocks["clinic_1"].start == time.fromisoformat(times["clinic_1"][0])


def test_the_solvers_own_priority_cannot_be_written_on_the_sheet():
    header = ["id", "description", "skedge", "priority", "weight", "tags", "created"]
    row = ["x", "", "REQUEST staff.dylan DO 'a' DURING block.clinic_1", "STABILITY", "", "", ""]
    with pytest.raises(LoadError, match="STABILITY is the solver's own"):
        parse_requests([header, row])
    assert parse_requests([header, [*row[:3], "HIGH", *row[4:]]])[0].priority.value == "HIGH"
