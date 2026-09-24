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
            "REQUEST ALL_OF staff.director NOT DO activities.clinics.all DURING blocks.clinic_1",
            "REQUEST ALL_OF staff.director NOT DO ANY activities.clinics.all DURING blocks.clinic_1",
        ),
        (
            "REQUEST AT_MOST 2 staff.all DO 'break' DURING EACH_OF blocks.all",
            "REQUEST AT_MOST 2 ANY staff.all DO 'break' DURING EACH_OF blocks.all",
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


def test_text_that_does_not_parse_is_left_alone(dataset):
    assert upgrade("REQUEST staff.rob NOT DO", dataset) == "REQUEST staff.rob NOT DO"
