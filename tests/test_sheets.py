import re
from datetime import date, time

import pytest

from puppet_strings.model import Offering, SkillStatus
from puppet_strings.names import normalize
from puppet_strings.sheets.blocks import parse_blocks
from puppet_strings.sheets.calendar import calendar_days, parse_calendar
from puppet_strings.sheets.clinic_data import parse_clinics
from puppet_strings.sheets.mappings import INDEX_COLUMNS
from puppet_strings.sheets.offerings import parse_offerings
from puppet_strings.sheets.published import assignment_rows, parse_published
from puppet_strings.sheets.skills import (
    ClinicPositions,
    known_skills,
    parse_position_skills,
    parse_skills,
    trainers,
)
from puppet_strings.sheets.source import (
    DAY_FIRST,
    MONTH_FIRST,
    CsvSource,
    LoadError,
    parse_date,
    parse_time,
)

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
    assert blocks["lunch"].day_types == {"weekday", "weekend"}
    assert blocks["lunch"].program_types == {"main_season", "other"}
    assert blocks["pack_out"].day_types == {"last_day"}
    assert blocks["clinic_1"].gap_to(blocks["clinic_4"]) == 315
    assert not blocks["clinic_1"].overlaps(blocks["clinic_2"])
    assert blocks["lunch"].overlaps(blocks["lunch"])
    assert blocks["pack_out"].overlaps(blocks["clinic_1"])


def test_mappings(dataset):
    preference = dataset.mappings["preference"]
    assert preference.keys == ("staff", "activities.clinics.all") and preference.numeric
    assert preference.normalized(("dylan", "archery_1_2")) == 1.0
    assert preference.normalized(("dylan", "candle_making")) == 0.5
    assert preference.default == 3 and preference.missing == 3
    assert preference.normalized(("dylan", "riflery")) == 0.5  # no row, so the default
    buddy = dataset.mappings["buddy"]
    assert not buddy.numeric and buddy.value == "{staff.all - staff.counselor}"
    assert buddy.rows == {("dylan",): "alan", ("james",): "sarah"}
    assert buddy.default == "AT_LEAST 1 {staff.all - staff.counselor - staff.director}"


def test_mapping_default_column(source):
    from puppet_strings.sheets.mappings import parse_mapping_index

    table = source.read("config", "Mappings")
    header, row = table[0], table[1]
    blank = [header, [c if header[i] != "default" else "" for i, c in enumerate(row)]]
    (mapping,) = parse_mapping_index(blank)
    assert mapping.default == 1 and mapping.normalized(("anyone", "anything")) == 0.0
    outside = [header, [c if header[i] != "default" else "9" for i, c in enumerate(row)]]
    with pytest.raises(LoadError, match="default 9 is outside 1..5"):
        parse_mapping_index(outside)
    without_column = [[c for c in header if c != "default"], row[: len(header) - 1]]
    (mapping,) = parse_mapping_index(without_column)
    assert mapping.default == 1


MAPPINGS_HEADER = list(INDEX_COLUMNS)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["x", "staff", "numeric", "", "", ""], "a numeric mapping needs scale_min and scale_max"),
        (["x", "staff", "staff", "1", "5", ""], "only a numeric mapping has a scale"),
        (["x", "", "staff", "", "", ""], "keys needs at least one set"),
        (["x", "mappings.buddy", "staff", "", "", ""], "names mappings"),
        (["x", "staff", "{staff.all - s}", "", "", ""], "should be a namespace"),
        (["x", "staff", "{staff.all -", "", "", ""], "unexpected input"),
    ],
)
def test_a_mapping_is_declared_with_sets_it_can_read(row, message):
    from puppet_strings.sheets.mappings import parse_mapping_index

    with pytest.raises(LoadError, match=re.escape(message)):
        parse_mapping_index([MAPPINGS_HEADER, row])


@pytest.mark.parametrize(
    ("tab", "rows", "message"),
    [
        ("mapping_buddy", [["key1", "value"], ["Dylan", "James"]], "'james' is not in {staff"),
        (
            "mapping_buddy",
            [["key1", "value"], ["Alan", "Sarah"]],
            "'alan' is not in staff.counselor",
        ),
        (
            "mapping_buddy",
            [["key1", "value"], ["Dyaln", "Sarah"]],
            "'dyaln' is not a name in staff",
        ),
        ("mapping_buddy", [["staff", "value"]], "missing columns ['key1']"),
        (
            "Mappings",
            [MAPPINGS_HEADER, ["buddy", "staff.counselor", "staff.all", "", "", "staff.all"]],
            "a default of more than one name needs ALL or a count",
        ),
        (
            "Mappings",
            [
                MAPPINGS_HEADER,
                [
                    "buddy",
                    "staff.counselor",
                    "{staff.support - staff.director}",
                    "",
                    "",
                    "AT_LEAST 1 staff.director",
                ],
            ],
            "reaches 'david', which is not in {staff.support - staff.director}",
        ),
        (
            "Mappings",
            [MAPPINGS_HEADER, ["buddy", "staff.counselor", "staff.all", "", "", "blocks.lunch"]],
            "names blocks, but the value is from staff",
        ),
    ],
)
def test_a_mapping_is_checked_against_the_day(fixtures_copy, tab, rows, message):
    from puppet_strings.sheets.load import load_dataset
    from tests.conftest import CONFIG, TARGET

    source = CsvSource(fixtures_copy)
    source.write("config", tab, rows)
    with pytest.raises(LoadError, match=re.escape(message)):
        load_dataset(source, CONFIG, TARGET)


def test_a_mapping_row_for_someone_resting_is_not_judged(fixtures_copy):
    """Staff resting all day are in no category, so whether they are a counselor is moot."""
    from puppet_strings.sheets.load import load_dataset
    from tests.conftest import CONFIG, TARGET

    source = CsvSource(fixtures_copy)
    rest = [
        ["date", "staff", "resting", "RAL_penalty", "note"],
        [str(TARGET), "Rob", "all day", "", ""],
    ]
    source.write("config", "Adjustments", rest)
    source.write("config", "mapping_buddy", [["key1", "value"], ["Dylan", "Rob"]])
    assert load_dataset(source, CONFIG, TARGET).mappings["buddy"].rows == {("dylan",): "rob"}


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
    ["name", "start date", "end date", "program type"],
    ["Session 1", "2026-09-13", "2026-09-26", "main season"],
    ["Session 2", "2026-09-27", "2026-10-03", "main season"],
    ["Family Camp", "2026-10-04", "2026-10-07", "other"],
]


def test_calendar_numbers_the_main_season_spans_in_sheet_order():
    spans = parse_calendar(CALENDAR)
    assert [s.id for s in spans] == ["session_1", "session_2", "family_camp"]
    assert [s.session for s in spans] == [1, 2, None]  # only the main season is numbered
    assert spans[0].start == date(2026, 9, 13) and spans[0].end == date(2026, 9, 26)


def test_a_span_is_every_day_between_its_ends():
    first, *_ = parse_calendar(CALENDAR)
    assert len(first.dates) == 14
    assert first.dates[0] == date(2026, 9, 13) and first.dates[-1] == date(2026, 9, 26)


def test_weeks_are_seven_days_from_the_start():
    first, _, other = parse_calendar(CALENDAR)
    assert first.weeks == 2
    assert first.week_of(date(2026, 9, 13)) == 1
    assert first.week_of(date(2026, 9, 19)) == 1
    assert first.week_of(date(2026, 9, 20)) == 2
    assert other.weeks == 1  # a span shorter than a week is one week


def test_a_day_knows_what_kinds_of_day_it_is():
    days = calendar_days(parse_calendar(CALENDAR))
    assert days[date(2026, 9, 13)].day_types == {"first_day", "weekend"}  # a Sunday start
    assert days[date(2026, 9, 16)].day_types == {"weekday"}
    assert days[date(2026, 9, 19)].day_types == {"weekend"}
    assert days[date(2026, 9, 26)].day_types == {"last_day", "weekend"}
    assert days[date(2026, 9, 16)].program_type == "main_season"
    assert days[date(2026, 10, 5)].program_type == "other"


def test_a_day_carries_its_span_session_and_week():
    days = calendar_days(parse_calendar(CALENDAR))
    assert days[date(2026, 9, 21)].span == "session_1"
    assert (days[date(2026, 9, 21)].session, days[date(2026, 9, 21)].week) == (1, 2)
    assert days[date(2026, 10, 5)].session is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["Extra", "2026-10-08", "2026-10-07", "other"], "is before start date"),
        (["Extra", "not a date", "2026-10-09", "other"], "must be YYYY-MM-DD"),
        (["Extra", "2026-10-08", "2026-10-09", "shoulder"], "program type must be one of"),
        (["Session 1", "2026-10-08", "2026-10-09", "main season"], "both named 'Session 1'"),
        (["Extra", "2026-09-20", "2026-09-21", "other"], "is in both 'Session 1' and 'Extra'"),
        (["Extra", "2026-10-08", "2027-04-08", "other"], "at most 20 are supported"),
        (["Target", "2026-10-08", "2026-10-09", "other"], "'dates.target' is already a name"),
        (["Session 4", "2026-10-08", "2026-10-09", "other"], "'dates.session_4' is"),
    ],
)
def test_calendar_rejects_a_span_it_cannot_read(row, message):
    with pytest.raises(LoadError, match=message):
        parse_calendar([*CALENDAR, row])


def test_a_row_with_no_name_is_an_error():
    with pytest.raises(LoadError, match="a row has no name"):
        parse_calendar([CALENDAR[0], ["", "2026-10-08", "2026-10-09", "other"]])


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
    assert dataset.block_categories["all_clinics"] == {
        "clinic_1",
        "clinic_2",
        "clinic_3",
        "clinic_4",
    }
    assert dataset.session_dates[0] == date(2026, 9, 13)
    assert len(dataset.session_dates) == 14  # a two-week session
    assert dataset.session == 1
    assert list(dataset.sessions) == [1, 2]
    assert dataset.this_span.id == "session_1"
    assert list(dataset.span_weeks(dataset.sessions[1])) == [1, 2]
    assert dataset.span_weeks(dataset.sessions[1])[2][0] == date(2026, 9, 20)
    assert dataset.week_dates == dataset.session_dates[:7]  # the target is in week 1
    assert [b.id for b in dataset.blocks_on(dataset.target)][:3] == [
        "breakfast",
        "clinic_1",
        "clinic_2",
    ]
    weekend = date(2026, 9, 19)  # a Saturday in the middle of the session
    assert [b.id for b in dataset.blocks_on(weekend)] == ["breakfast", "lunch", "playstation"]
    last = date(2026, 9, 26)  # the session's last day, which is when pack-out runs
    assert "pack_out" in [b.id for b in dataset.blocks_on(last)]
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


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("2026-06-14", date(2026, 6, 14)),  # what the sheet holds underneath
        ("2026/06/14", date(2026, 6, 14)),
        ("6/14/2026", date(2026, 6, 14)),  # a date column in a sheet set to the US
        ("06/14/2026", date(2026, 6, 14)),
        ("6/14/26", date(2026, 6, 14)),
        ("14/6/2026", date(2026, 6, 14)),  # day first, and unambiguous, so it is read so
        ("14 Jun 2026", date(2026, 6, 14)),
        ("14 June 2026", date(2026, 6, 14)),
        ("June 14, 2026", date(2026, 6, 14)),
        ("Sunday, June 14, 2026", date(2026, 6, 14)),
        ("14-Jun-2026", date(2026, 6, 14)),
        ("6/14/2026 0:00:00", date(2026, 6, 14)),  # a date cell carrying a midnight
        ("6/14/2026 12:00 AM", date(2026, 6, 14)),
        ("46187", date(2026, 6, 14)),  # an unformatted date cell, as its serial number
        ("  2026-06-14  ", date(2026, 6, 14)),
    ],
)
def test_a_date_is_read_however_the_sheet_writes_it(written, expected):
    assert parse_date(written, "Calendar") == expected


def test_an_ambiguous_numeric_date_follows_the_declared_order():
    """6/7/2026 is two different days, and only the sheet's own locale says which."""
    assert parse_date("6/7/2026", "Calendar", MONTH_FIRST) == date(2026, 6, 7)
    assert parse_date("6/7/2026", "Calendar", DAY_FIRST) == date(2026, 7, 6)
    # one that cannot be read both ways is read the same whichever order is declared
    for order in (MONTH_FIRST, DAY_FIRST):
        assert parse_date("14/6/2026", "Calendar", order) == date(2026, 6, 14)


@pytest.mark.parametrize(
    "written", ["", "   ", "the fourteenth", "2026-13-01", "6/31/2026", "20260614", "0"]
)
def test_a_date_that_is_not_a_date_says_so(written):
    with pytest.raises(LoadError, match="Calendar"):
        parse_date(written, "Calendar")


def test_a_calendar_formatted_as_dates_loads():
    """A Calendar whose date columns are real date cells, displayed as the sheet shows them."""
    table = [
        ["name", "start date", "end date", "program type"],
        ["Session 1", "6/14/2026", "6/27/2026", "main season"],
        ["Family Camp", "September 1, 2026", "September 5, 2026", "other"],
    ]
    first, other = parse_calendar(table)
    assert (first.start, first.end) == (date(2026, 6, 14), date(2026, 6, 27))
    assert (other.start, other.end) == (date(2026, 9, 1), date(2026, 9, 5))


def test_the_date_order_setting_is_checked(tmp_path):
    from puppet_strings.config import load_config

    path = tmp_path / "config.toml"
    path.write_text('[day]\ndate_order = "ymd"\n')
    with pytest.raises(ValueError, match="date_order must be one of"):
        load_config(path)
    path.write_text('[day]\ndate_order = "dmy"\n')
    assert load_config(path).date_order == "dmy"


class CountingSource:
    """Wraps a source and records which sheets it was asked for."""

    def __init__(self, inner):
        self.inner, self.asked = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def read(self, sheet, tab):
        self.asked.append(sheet)
        return self.inner.read(sheet, tab)

    def read_many(self, sheet, tabs):
        self.asked.append(sheet)
        return self.inner.read_many(sheet, tabs)

    def read_group(self, folder, tab):
        self.asked.append(folder)
        return self.inner.read_group(folder, tab)


def test_a_date_off_the_calendar_is_caught_before_anything_else_is_read(source):
    """The Calendar is read first, so a date camp is not running fails at once."""
    from puppet_strings.config import Config
    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import NotACampDay

    counting = CountingSource(source)
    with pytest.raises(NotACampDay, match="2026-12-25 is not a camp day"):
        load_dataset(counting, Config(), date(2026, 12, 25))
    assert counting.asked == ["config"]  # nothing else was fetched


def test_a_date_off_the_calendar_says_what_to_try_instead(source):
    from puppet_strings.config import Config
    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import NotACampDay

    with pytest.raises(NotACampDay) as info:
        load_dataset(source, Config(), date(2026, 12, 25))
    assert "The calendar runs 2026-09-13 to 2026-10-03" in str(info.value)
    assert "nearest camp day is 2026-10-03" in str(info.value)


def test_a_camp_day_is_not_an_error(source):
    from puppet_strings.config import Config
    from puppet_strings.sheets.load import load_dataset

    assert load_dataset(source, Config(), date(2026, 9, 16)) is not None


def test_an_empty_calendar_says_so():
    from puppet_strings.sheets.load import check_camp_day
    from puppet_strings.sheets.source import NotACampDay

    with pytest.raises(NotACampDay, match="no rows, so no date is a camp day"):
        check_camp_day(date(2026, 9, 16), {})


def test_not_a_camp_day_is_still_a_load_error():
    """Anything catching LoadError keeps catching it; the command line prints it the same."""
    from puppet_strings.sheets.source import NotACampDay

    assert issubclass(NotACampDay, LoadError)


def test_staff_all_is_who_the_categories_sheet_names(dataset):
    """The Skills sheet keeps everyone who ever worked here; the span says who is here now."""
    assert dataset.staff_categories["all"] == set(dataset.staff)  # the fixture camp is whole


def test_somebody_in_no_category_is_away(fixtures_copy):
    import csv

    from puppet_strings.config import Config
    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import CsvSource

    where = fixtures_copy / "root/2026/Main Season/Session 1/Staff Categories/Categories.csv"
    rows = list(csv.reader(where.open(newline="")))
    support = rows[0].index("support")
    for row in rows[1:]:  # send everyone in `support` home, Alan among them
        row[support] = ""
    with where.open("w", newline="") as f:
        csv.writer(f).writerows(rows)

    config = Config(folders={"root": "root", "cabin_acts": "cabin_acts"})
    loaded = load_dataset(CsvSource(fixtures_copy), config, date(2026, 9, 16))
    assert "alan" in loaded.staff  # still a name, so a request naming him still resolves
    assert "alan" not in loaded.staff_categories["all"]
    assert "alan" not in loaded.staff_categories["clinic_trainers"]
    # away is the same as resting all day, so no position can be filled by him
    assert loaded.staff["alan"].resting_blocks == {b.id for b in loaded.blocks_on(loaded.target)}
    assert not loaded.holds("alan", loaded.target, "clinic_1")
    assert any("in no category this span, so they are away" in w for w in loaded.warnings)
    assert "alan" in loaded.away and "alan" not in loaded.at_camp  # and off the published views


def test_a_load_can_leave_the_days_behind_it_for_later(source):
    """The window reads none of them and there is a spreadsheet of them per day of a season."""
    from puppet_strings.sheets.load import load_dataset, read_history
    from tests.conftest import CONFIG

    target = date(2026, 9, 15)
    quick = load_dataset(source, CONFIG, target, history=False)
    assert quick.published == {}
    assert quick.baseline is not None  # but the target's own day is read, and says so

    filled = read_history(source, CONFIG, quick)
    assert set(filled.published) == {date(2026, 9, 14)}
    assert filled.baseline == quick.baseline
    assert read_history(source, CONFIG, filled) is filled  # asked once, not once per solve
    assert load_dataset(source, CONFIG, target).published == filled.published


def test_a_cabin_act_at_rest_hour_says_so_at_one_end_of_its_title():
    from datetime import date as _date

    from puppet_strings.sheets.cabin_acts import CabinAct, _activity

    def read(title: str) -> tuple[bool, list[str]]:
        act = CabinAct("M2", "monday", title, ("hero",))
        activity, said = _activity(act, _date(2026, 9, 14), "Board", {}, {"hero": frozenset()}, {})
        return activity.rest_hour, said

    for title in ("RH: Fruit Ninja", "RH - Bubble Lake", "REST HOUR Mafia", "Stranded - Rest Hour"):
        assert read(title) == (True, [])
    assert read("Rhythm Game") == (False, [])
    rest_hour, (told,) = read("CA: Blackberry picking, RH: muffins")
    assert not rest_hour and "mentions rest hour in the middle" in told


def test_a_cabin_act_warns_only_when_a_hero_is_actually_dropped():
    """Six heroes fill the six positions and nothing is lost; the seventh is what is lost."""
    from datetime import date as _date

    from puppet_strings.model import POSITION_ROLES
    from puppet_strings.sheets.cabin_acts import CabinAct, _activity

    categories = {f"hero_{i}": frozenset({"dylan"}) for i in range(8)}

    def warnings_for(count: int) -> list[str]:
        act = CabinAct("M2", "monday", "", tuple(f"hero_{i}" for i in range(count)))
        activity, said = _activity(act, _date(2026, 9, 14), "Board", {}, categories, {})
        assert len(activity.positions) == min(count, len(POSITION_ROLES))
        return said

    assert warnings_for(len(POSITION_ROLES)) == []
    (told,) = warnings_for(len(POSITION_ROLES) + 1)
    assert "asks for more heroes than positions" in told


def test_a_cabin_act_sheet_that_cannot_be_read_is_said_out_loud(tmp_path):
    """Losing every cabin act in camp is not something to do quietly."""
    import shutil

    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, FIXTURES, TARGET

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    board = next((copy / "cabin_acts").glob("*/Board.csv"))
    board.rename(board.with_name("Bored.csv"))  # a tab renamed by somebody tidying up
    dataset = load_dataset(CsvSource(copy), CONFIG, TARGET)
    assert any("cabin acts: no cabin act runs today" in w for w in dataset.warnings)
    assert not any(a.category == "cabin_act" for a in dataset.activities.values())


def test_no_cabin_act_folder_is_no_cabin_acts_and_nothing_said(tmp_path):
    """An install with no cabin act folder at all has nothing to warn about."""
    import shutil

    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, FIXTURES, TARGET

    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    shutil.rmtree(copy / "cabin_acts")
    dataset = load_dataset(CsvSource(copy), CONFIG, TARGET)
    assert not any(a.category == "cabin_act" for a in dataset.activities.values())
    assert not any("cabin act" in w for w in dataset.warnings)


def test_a_published_cabin_act_is_read_as_the_one_on_that_day():
    """Two cabin acts share a name and differ by date, so the date has to break the tie."""
    from datetime import date as _date

    from puppet_strings.model import Activity, Staff
    from puppet_strings.sheets.published import COLUMNS as PUBLISHED
    from puppet_strings.sheets.published import parse_published

    def act(day):
        return Activity(
            name="M2 CA",
            id=f"cabin_act_m2_{day}",
            category="cabin_act",
            slots=0,
            positions=(),
            cabin="M2",
            day=day,
        )

    monday, tuesday = _date(2026, 9, 14), _date(2026, 9, 15)
    activities = {a.id: a for a in (act(monday), act(tuesday))}
    staff = {"dylan": Staff(id="dylan", name="Dylan", ral=1, skills={})}
    table = [
        list(PUBLISHED),
        ["Dylan", "M2 CA", "first", "cabin_act", "19:00", "60", "request"],
    ]
    (monday_row,) = parse_published(table, monday, staff, activities)
    (tuesday_row,) = parse_published(table, tuesday, staff, activities)
    assert monday_row.activity == f"cabin_act_m2_{monday}"
    assert tuesday_row.activity == f"cabin_act_m2_{tuesday}"


def test_a_load_lists_each_span_folder_once(source):
    """Listing is a Drive request, and a season has hundreds of days behind it."""
    from puppet_strings.sheets.load import load_dataset
    from puppet_strings.sheets.source import CsvSource
    from tests.conftest import CONFIG, TARGET

    class Counting(CsvSource):
        def __init__(self, root):
            super().__init__(root)
            self.listed = []

        def documents(self, root, path):
            self.listed.append(path)
            return super().documents(root, path)

    counting = Counting(source.root)
    load_dataset(counting, CONFIG, TARGET)
    assert counting.listed  # it does list the span the target is in
    assert len(counting.listed) == len(set(counting.listed))
