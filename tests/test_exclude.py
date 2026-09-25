"""Taking the people an EXCLUDE names out of the days it names."""

from dataclasses import replace
from datetime import date

from puppet_strings.exclude import apply_exclusions, mentions_exclusion
from puppet_strings.model import Priority, Request

TARGET = date(2026, 9, 16)

ALL_DAY = "EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks ON dates.target"
MORNING = (
    "EXCLUDE staff.alan DO 'dentist' DURING ALL {blocks.clinic_1 + blocks.clinic_2} ON dates.target"
)


def away(dataset, *skedges):
    """The dataset with some exclusion requests added to it and applied."""
    requests = tuple(
        Request(f"away-{i}", "", text, Priority.MUST_HAPPEN) for i, text in enumerate(skedges)
    )
    return apply_exclusions(replace(dataset, requests=dataset.requests + requests))


def test_a_whole_day_off(dataset):
    ds = away(dataset, ALL_DAY)
    assert all(not ds.holds("dylan", TARGET, b.id) for b in ds.blocks_on(TARGET))
    assert ds.excused("dylan", "clinic_1") == "offsite"
    # and out of every category, so a request written about staff asks nothing of him
    assert "dylan" not in ds.staff_categories["all"]
    assert not any("dylan" in members for members in ds.staff_categories.values())
    assert "dylan" in ds.staff  # still a name, so a request naming him still resolves


def test_part_of_a_day_off(dataset):
    """Somebody who is back after lunch is still at camp, and still owed their breaks."""
    ds = away(dataset, MORNING)
    assert not ds.holds("alan", TARGET, "clinic_1") and not ds.holds("alan", TARGET, "clinic_2")
    assert ds.holds("alan", TARGET, "clinic_3")
    assert ds.excused("alan", "clinic_1") == "dentist" and ds.excused("alan", "clinic_3") == ""
    assert "alan" in ds.staff_categories["all"]


def test_a_day_nobody_is_excluded_from_is_left_exactly_as_it_was(dataset):
    assert apply_exclusions(dataset) is dataset


def test_applying_the_same_exclusions_again_changes_nothing(dataset):
    """The load applies them and so does the solve, so it has to be safe to do twice."""
    once = away(dataset, ALL_DAY, MORNING)
    twice = apply_exclusions(once)
    assert twice.excluded == once.excluded
    assert twice.staff_categories == once.staff_categories
    assert twice.resting == once.resting


def test_a_block_the_day_does_not_have_is_no_block_to_be_taken_out_of(dataset):
    """`blocks` is the Blocks sheet; a day only has the blocks that run on it."""
    ds = away(dataset, ALL_DAY)
    running = {b.id for b in ds.blocks_on(TARGET)}
    assert set(ds.excluded[TARGET]["dylan"]) == running
    assert ds.staff["dylan"].resting_blocks == running


def test_excluding_everybody_in_a_category_on_several_dates(dataset):
    text = (
        "EXCLUDE EACH staff.counselor DO 'training' "
        "DURING ALL blocks.all_clinics ON ALL dates.session_1.week_1"
    )
    ds = away(dataset, text)
    assert len(ds.excluded) > 1  # every date of the week, not just the one being scheduled
    counselors = dataset.staff_categories["counselor"]
    assert set(ds.excluded[TARGET]) == set(counselors)
    assert ds.excused(next(iter(counselors)), "clinic_1") == "training"


def test_a_date_that_is_not_a_camp_day_holds_nobody(dataset):
    ds = away(dataset, ALL_DAY.replace("dates.target", "2026-12-25"))
    assert ds.excluded == {} and ds is not None


def test_a_request_that_does_not_parse_is_left_to_the_validator(dataset):
    """A broken request elsewhere is no reason for a day to forget who is away."""
    broken = Request("broken", "", "EXCLUDE nonsense", Priority.MUST_HAPPEN)
    ds = apply_exclusions(replace(dataset, requests=(*dataset.requests, broken)))
    assert ds.excluded == {}


def test_what_is_worth_parsing(dataset):
    assert mentions_exclusion("EXCLUDE staff.dylan DO 'x'")
    assert mentions_exclusion("exclude staff.dylan do 'x'")
    assert not mentions_exclusion("REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
