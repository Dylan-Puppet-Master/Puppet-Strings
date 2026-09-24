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
        (
            "d: EACH_OF dates.season.sundays\nREQUEST ANY 1 {staff.rob + (ALL_OF staff.director)} DO 'x' ON d",
            "d: EACH dates.season.sundays\nREQUEST AT_LEAST 1 {staff.rob + (ALL staff.director)} DO 'x' ON d",
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
            "REQUEST ALL {staff.lucy + staff.tom} DO 'x' DURING AT_LEAST 2 CONSECUTIVE blocks.all",
        ),
        (  # no DURING was the whole day, and still is
            "REQUEST AT_MOST 3 CONSECUTIVE EACH staff.all DO activities.clinics.all",
            "REQUEST EACH staff.all DO ANY activities.clinics.all "
            "DURING AT_MOST 3 CONSECUTIVE blocks.all",
        ),
        (
            "EACH s IN staff.all\nIF AT_LEAST 3 CONSECUTIVE s DO activities.clinics.all\n"
            "REQUEST s FREE DURING ANY 1 blocks.all",
            "EACH s IN staff.all\nIF s DO ANY activities.clinics.all "
            "DURING AT_LEAST 3 CONSECUTIVE blocks.all\nREQUEST s FREE DURING AT_LEAST 1 blocks.all",
        ),
        (  # a DURING it had already is where the run is measured
            "PREFER AT_LEAST 2h CONSECUTIVE staff.dylan DO 'x' DURING blocks.all_clinics",
            "PREFER staff.dylan DO 'x' DURING ANY CONSECUTIVE blocks.all_clinics FOR AT_LEAST 2h",
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


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (  # the one set it pooled
            "REQUEST AT_MOST 2 ANY staff.counselor DO 'break' DURING EACH blocks.all",
            "REQUEST AT_MOST 2 staff.counselor DO 'break' DURING EACH blocks.all",
        ),
        (  # no DURING: the blocks of the whole day
            "REQUEST EXACTLY 3 EACH staff.counselor DO 'break'",
            "REQUEST EACH staff.counselor DO 'break' DURING EXACTLY 3 blocks.all",
        ),
        (  # a person runs one clinic a block, so the blocks, not the clinics
            "PREFER AT_MOST 1 EACH staff.all DO ANY activities.clinics.all",
            "PREFER EACH staff.all DO ANY activities.clinics.all DURING AT_MOST 1 blocks.all",
        ),
        (  # measured in runs
            "REQUEST AT_MOST 1 EACH staff.all DO ANY activities.clinics.all "
            "DURING ANY CONSECUTIVE blocks.all",
            "REQUEST EACH staff.all DO ANY activities.clinics.all "
            "DURING AT_MOST 1 CONSECUTIVE blocks.all",
        ),
        (  # after DO, the same
            "IF staff.dylan DO AT_LEAST 3 ANY activities.clinics.all "
            "DURING ANY CONSECUTIVE blocks.all\nREQUEST staff.dylan FREE DURING blocks.playstation",
            "IF staff.dylan DO ANY activities.clinics.all DURING AT_LEAST 3 CONSECUTIVE blocks.all"
            "\nREQUEST staff.dylan FREE DURING blocks.playstation",
        ),
        (  # one block, counted once, in front of the block
            "PREFER AT_LEAST 1 staff.dylan DO activities.clinics.riflery DURING blocks.clinic_2",
            "PREFER staff.dylan DO activities.clinics.riflery DURING AT_LEAST 1 blocks.clinic_2",
        ),
        (  # a length goes on FOR
            "REQUEST AT_LEAST 2h staff.dylan DO 'video editing'",
            "REQUEST staff.dylan DO 'video editing' FOR AT_LEAST 2h",
        ),
        (  # over pooled dates, a count of blocks is of each block on each date
            "REQUEST AT_LEAST 2 staff.dylan DO 'x' ON ANY {2026-09-16 .. 2026-09-17}",
            "REQUEST staff.dylan DO 'x' ON ANY {2026-09-16 .. 2026-09-17} "
            "DURING AT_LEAST 2 blocks.all",
        ),
        (
            "PREFER AT_MOST 8 EACH staff.all DO ANY activities.clinics.all "
            "DURING ANY blocks.all_clinics ON ANY dates.session_1.all",
            "PREFER EACH staff.all DO ANY activities.clinics.all "
            "DURING AT_MOST 8 blocks.all_clinics ON ANY dates.session_1.all",
        ),
        (  # people and blocks are two pools: no spelling now, so left as it was
            "REQUEST AT_MOST 2 ANY staff.counselor DO 'break'",
            "REQUEST AT_MOST 2 ANY staff.counselor DO 'break'",
        ),
    ],
)
def test_a_count_moves_onto_the_set_it_counts(dataset, old, new):
    assert upgrade(old, dataset) == new


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "REQUEST ANY 3 staff.counselor DO 'lifeguard' DURING blocks.rest_hour",
            "REQUEST AT_LEAST 3 staff.counselor DO 'lifeguard' DURING blocks.rest_hour",
        ),
        (
            "ANY 1 v IN {staff.dylan + staff.rob}\nx: ANY 2 staff.counselor\n"
            "REQUEST ALL {staff.alesa + v} DO 'video' DURING ANY 1 blocks.all",
            "EXACTLY 1 v IN {staff.dylan + staff.rob}\nx: EXACTLY 2 staff.counselor\n"
            "REQUEST ALL {staff.alesa + v} DO 'video' DURING AT_LEAST 1 blocks.all",
        ),
        (  # the block was one choice for both people, so it is named once
            "REQUEST ANY 2 staff.counselor DO 'x' DURING ANY 1 blocks.all",
            "EXACTLY 1 chosen_1 IN blocks.all\n"
            "REQUEST AT_LEAST 2 staff.counselor DO 'x' DURING chosen_1",
        ),
        (  # one date chosen, so the block after it is that date's own
            "REQUEST staff.dylan DO 'x' DURING ANY 1 blocks.all ON ANY 1 dates.session_1.all",
            "REQUEST staff.dylan DO 'x' DURING AT_LEAST 1 blocks.all "
            "ON AT_LEAST 1 dates.session_1.all",
        ),
        (  # a run shared by two people has no binding: left whole, not half rewritten
            "REQUEST ANY 2 staff.counselor DO 'x' DURING ANY 3 blocks.all CONSECUTIVE",
            "REQUEST ANY 2 staff.counselor DO 'x' DURING ANY 3 CONSECUTIVE blocks.all",
        ),
        (
            "REQUEST staff.rob DO 'x' WITH ANY 2 staff.counselor DURING blocks.clinic_1",
            "REQUEST staff.rob DO 'x' WITH AT_LEAST 2 staff.counselor DURING blocks.clinic_1",
        ),
        (
            "REQUEST ALL {staff.charlton + (ANY 1 {staff.dylan + staff.rob})} DO 'x' "
            "DURING blocks.lunch",
            "REQUEST ALL {staff.charlton + (AT_LEAST 1 {staff.dylan + staff.rob})} DO 'x' "
            "DURING blocks.lunch",
        ),
    ],
)
def test_any_n_is_a_count_or_a_binding(dataset, old, new):
    assert upgrade(old, dataset) == new


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (  # right of NOT a pool was every block of it
            "REQUEST staff.hails NOT FREE DURING ANY blocks.evening",
            "REQUEST staff.hails BUSY DURING ALL blocks.evening",
        ),
        (  # and ALL was all of them together, so at least one is busy
            "REQUEST staff.hails NOT FREE DURING ALL blocks.evening",
            "REQUEST staff.hails BUSY DURING AT_LEAST 1 blocks.evening",
        ),
        (  # no DURING was every block
            "REQUEST staff.hails NOT FREE",
            "REQUEST staff.hails BUSY DURING ALL blocks.all",
        ),
        (
            "REQUEST AT_MOST 4 EACH staff.director NOT FREE",
            "REQUEST EACH staff.director BUSY DURING AT_MOST 4 blocks.all",
        ),
    ],
)
def test_not_free_is_busy(dataset, old, new):
    assert upgrade(old, dataset) == new


def test_what_describes_the_activity_moves_after_the_verb(dataset):
    old = "REQUEST staff.rob FOR 30m WITH staff.dylan DO 'break' DURING blocks.clinic_1"
    new = "REQUEST staff.rob DO 'break' DURING blocks.clinic_1 FOR EXACTLY 30m WITH staff.dylan"
    assert upgrade(old, dataset) == new


def test_a_role_after_with_was_the_subjects_and_stays_so(dataset):
    old = "REQUEST staff.rob DO activities.clinics.riflery WITH staff.vic AS_ROLE roles.first DURING blocks.clinic_1"
    new = "REQUEST staff.rob DO activities.clinics.riflery AS_ROLE roles.first WITH staff.vic DURING blocks.clinic_1"
    assert upgrade(old, dataset) == new


def test_a_bare_for_was_exactly_that_long(dataset):
    old = "REQUEST EACH staff.all DO 'break' FOR 30m DURING ANY 3 blocks.all"
    new = "REQUEST EACH staff.all DO 'break' FOR EXACTLY 30m DURING AT_LEAST 3 blocks.all"
    assert upgrade(old, dataset) == new
    assert upgrade("REQUEST staff.rob DO 'x' FOR 1h DURING blocks.clinic_1", dataset) == (
        "REQUEST staff.rob DO 'x' FOR EXACTLY 1h DURING blocks.clinic_1"
    )
