from datetime import date, time

import pytest

from puppet_strings.model import Offering, SkillStatus
from puppet_strings.sheets.blocks import parse_blocks
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import assignment_rows, parse_published
from puppet_strings.sheets.requests import parse_requests, request_rows
from puppet_strings.sheets.skills import parse_position_skills, parse_skills, trainers
from puppet_strings.sheets.source import LoadError


def test_skills_statuses(source):
    staff, warnings = parse_skills(source.read("skills", "Skills"))
    assert staff["alan"].skills["Canopy Tour 1st"] is SkillStatus.CHECKED_OFF
    assert staff["alan"].skills["Gravity Zip Line 1st"] is SkillStatus.CHECKED_OFF
    assert staff["audrey"].skills["Candle making"] is SkillStatus.TRAINER
    assert staff["cam_vl"].skills["Ceramics Wheel"] is SkillStatus.NEEDS_SCAFFOLD
    assert staff["cam_vl"].skills["Candle making"] is SkillStatus.NEEDS_SCAFFOLD
    assert staff["paul"].skills["Candle making"] is SkillStatus.NEEDS_SHADOW
    assert staff["brian"].skills["Riflery"] is SkillStatus.CHECKED_OFF
    assert staff["dylan"].skills["Riflery"] is SkillStatus.NONE
    assert staff["alesa"].skills["LIFEGUARD"] is SkillStatus.CHECKED_OFF
    assert "Canopy Tour" not in staff["alan"].skills  # date columns are skipped
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
    skills = parse_position_skills(source.read("skills", "Positions"))
    assert skills["Gravity Zip Line"] == ("Gravity Zip Line 1st", "Gravity Zip Line 2nd", None)
    assert skills["Low Ropes"] == ("Low Ropes", None, None)


def test_clinics(source):
    skills = parse_position_skills(source.read("skills", "Positions"))
    activities = parse_clinics(source.read("clinic_data", "Clinics"), skills)
    zip_line = activities["gravity_zip_line"]
    assert [p.role for p in zip_line.positions] == ["first", "second"]
    assert [p.ral for p in zip_line.positions] == [5, 3]
    assert zip_line.positions[1].skill == "Gravity Zip Line 2nd"
    assert activities["blacksmithing_dbl"].double
    canoe = activities["canoe_1_2"]
    assert [(p.role, p.skill, p.ral) for p in canoe.positions] == [
        ("first", "Canoe", 5),
        ("lifeguard", "LIFEGUARD", 5),
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
        parse_clinics(table, {})


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


def test_offerings_reject_lone_double(dataset):
    table = [["WEDNESDAY"], ["Clinic 1", "Clinic 2"], ["Blacksmithing (DBL)", ""]]
    with pytest.raises(LoadError, match="only in clinic_1"):
        parse_offerings(table, dataset.activities, set(dataset.blocks), "Wednesday")


def test_blocks(source):
    blocks = parse_blocks(source.read("config", "Blocks"))
    assert blocks["clinic_1"].start == time(9, 15)
    assert blocks["clinic_1"].minutes == 75
    assert blocks["pm_break"].display_group == "break_then_work_projects"
    assert blocks["pm_break"].categories == {"any", "break_slots"}
    assert blocks["clinic_1"].gap_to(blocks["clinic_4"]) == 315
    assert not blocks["clinic_1"].overlaps(blocks["clinic_2"])
    assert blocks["pm_break"].overlaps(blocks["pm_break"])


def test_requests_round_trip(source):
    table = source.read("config", "Requests")
    requests = parse_requests(table)
    assert requests[0].id == "counselor-hours"
    assert requests[0].weight == 1.0
    assert requests[3].weight == 0.5
    assert requests[0].created == date(2026, 9, 1)
    assert parse_requests(request_rows(requests)) == requests


def test_requests_reject_weight_on_hard():
    table = [
        ["id", "description", "skedge", "priority", "weight", "created"],
        ["x", "", "TASK FREE", "MUST_HAPPEN", "2", ""],
    ]
    with pytest.raises(LoadError, match="not allowed with MUST_HAPPEN"):
        parse_requests(table)


def test_metrics(dataset):
    enjoyment = dataset.metrics["enjoyment"]
    assert enjoyment.keys == ("staff", "activity")
    assert enjoyment.normalized(("dylan", "archery_1_2")) == 1.0
    assert enjoyment.normalized(("dylan", "candle_making")) == 0.5
    assert enjoyment.normalized(("dylan", "riflery")) == 0.0


def test_published_round_trip(dataset, source):
    yesterday = date(2026, 9, 15)
    assignments = dataset.published[yesterday]
    assert len(assignments) == 5
    hour = next(a for a in assignments if a.activity == "counselor hour")
    assert hour.staff == "dylan" and hour.role is None and hour.block == "clinic_2"
    rows = assignment_rows(assignments, dataset.staff, dataset.activities)
    assert set(map(tuple, rows[1:])) == set(map(tuple, source.read("published", "2026-09-15")[1:]))
    assert set(parse_published(rows, yesterday, dataset.staff, dataset.activities)) == set(
        assignments
    )


def test_dataset(dataset):
    assert dataset.staff_categories["counselor"] == {"dylan", "james", "paul"}
    assert dataset.staff_categories["village_hero"] == {"audrey", "mogee"}
    assert dataset.staff_categories["clinic_trainers"] == {"audrey", "alexis"}
    assert "etc" not in dataset.staff_categories
    assert len(dataset.staff_categories["all"]) == 17
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
    assert len(dataset.session_dates) == 7
    assert [b.id for b in dataset.blocks_on(dataset.target)][:3] == [
        "clinic_1",
        "clinic_2",
        "lunch_break",
    ]
    assert set(dataset.published) == {date(2026, 9, 14), date(2026, 9, 15)}
