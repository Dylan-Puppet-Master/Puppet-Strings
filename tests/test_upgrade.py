import pytest

from puppet_strings.skedge.upgrade import upgrade


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "REQUEST staff.rob NOT DO 'break' DURING blocks.meals",
            "REQUEST staff.rob NOT DO 'break' DURING ANY blocks.meals",
        ),
        (  # the subject is left of NOT and chooses; one block is one thing
            "REQUEST ALL staff.director NOT DO activities.clinics.all DURING blocks.clinic_1",
            "REQUEST ALL staff.director NOT DO ANY activities.clinics.all DURING blocks.clinic_1",
        ),
        (
            "REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH blocks.all",
            "REQUEST AT_MOST 2 ANY staff.all DO 'break' DURING EACH blocks.all",
        ),
        (  # a clause written ahead of the amount is the pattern's
            "PREFER ON {2026-09-14 .. 2026-09-18} AT_MOST 1 staff.dylan DO activities.clinics.all",
            "PREFER ON ANY {2026-09-14 .. 2026-09-18} AT_MOST 1 staff.dylan DO ANY activities.clinics.all",
        ),
        (  # WITH counts, so it keeps what it has; a named set is a set
            "crew: {staff.lucy + staff.tom}\nIF crew FREE DURING blocks.lunch\n"
            "REQUEST staff.rob NOT DO 'x' WITH staff.lucy",
            "crew: {staff.lucy + staff.tom}\nIF ANY crew FREE DURING blocks.lunch\n"
            "REQUEST staff.rob NOT DO 'x' WITH staff.lucy",
        ),
        (  # a date and a date offset are one thing each
            "REQUEST staff.rob NOT DO 'x' ON {dates.target - 1d}",
            "REQUEST staff.rob NOT DO 'x' ON {dates.target - 1d}",
        ),
    ],
)
def test_matched_sets_take_any(dataset, old, new):
    assert upgrade(old, dataset) == new
    assert upgrade(new, dataset) == new  # already up to date


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "REQUEST ALL_OF staff.director DO 'x' DURING blocks.clinic_1 ON EACH_OF dates.season.all",
            "REQUEST ALL staff.director DO 'x' DURING blocks.clinic_1 ON EACH dates.season.all",
        ),
        (
            "each_of d IN dates.season.sundays\nREQUEST staff.rob DO 'x' DURING all_of blocks.meals ON d",
            "EACH d IN dates.season.sundays\nREQUEST staff.rob DO 'x' DURING ALL blocks.meals ON d",
        ),
        (  # with another rewrite beside it
            "REQUEST staff.rob DO 'x' DURING ALL_OF blocks.meals CONSECUTIVE",
            "REQUEST staff.rob DO 'x' DURING ALL CONSECUTIVE blocks.meals",
        ),
        (
            "d: EACH_OF dates.season.sundays\nREQUEST ANY 1 {staff.rob + (ALL_OF staff.director)} DO 'x' ON d",
            "d: EACH dates.season.sundays\nREQUEST ANY 1 {staff.rob + (ALL staff.director)} DO 'x' ON d",
        ),
    ],
)
def test_all_of_and_each_of_lose_their_of(dataset, old, new):
    assert upgrade(old, dataset) == new


def test_text_that_does_not_parse_is_left_alone(dataset):
    assert upgrade("REQUEST staff.rob NOT DO", dataset) == "REQUEST staff.rob NOT DO"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "REQUEST ALL {staff.lucy + staff.tom} DO 'x' DURING ANY 2 blocks.all CONSECUTIVE",
            "REQUEST ALL {staff.lucy + staff.tom} DO 'x' DURING ANY 2 CONSECUTIVE blocks.all",
        ),
        (  # no DURING was the whole day, and still is
            "REQUEST AT_MOST 3 CONSECUTIVE EACH staff.all DO activities.clinics.all",
            "REQUEST AT_MOST 3 EACH staff.all DO ANY activities.clinics.all "
            "DURING ANY CONSECUTIVE blocks.all",
        ),
        (
            "EACH s IN staff.all\nIF AT_LEAST 3 CONSECUTIVE s DO activities.clinics.all\n"
            "REQUEST s FREE DURING ANY 1 blocks.all",
            "EACH s IN staff.all\nIF AT_LEAST 3 s DO ANY activities.clinics.all "
            "DURING ANY CONSECUTIVE blocks.all\nREQUEST s FREE DURING ANY 1 blocks.all",
        ),
        (  # a DURING it had already is where the run is measured
            "PREFER AT_LEAST 2h CONSECUTIVE staff.dylan DO 'x' DURING blocks.all_clinics",
            "PREFER AT_LEAST 2h staff.dylan DO 'x' DURING ANY CONSECUTIVE blocks.all_clinics",
        ),
        (  # wrong before, and moved rather than dropped, so still wrong and still says so
            "REQUEST staff.dylan DO 'x' DURING ALL blocks.all CONSECUTIVE",
            "REQUEST staff.dylan DO 'x' DURING ALL CONSECUTIVE blocks.all",
        ),
    ],
)
def test_consecutive_moves_onto_the_blocks(dataset, old, new):
    assert upgrade(old, dataset) == new
    assert upgrade(new, dataset) == new
