"""Requests that ask for something the sheets rule out, found without solving."""

from datetime import date

from puppet_strings.app.errors import find_errors, summary
from puppet_strings.app.facets import resolve_request
from tests.build import request as req

TARGET = date(2026, 9, 16)

# Dylan is checked off on archery and not on riflery; the day runs archery in clinic 1 and
# riflery in clinic 3, and does not run Muay Thai at all.
ARCHERY = "REQUEST staff.dylan DO activities.clinics.archery_1_2 DURING blocks.clinic_1"
RIFLERY = "REQUEST staff.dylan DO activities.clinics.riflery DURING blocks.clinic_3"


def found(dataset, *requests):
    """Every error among some requests, with the fixture's own requests left out."""
    resolved = {r.id: resolve_request(r, dataset)[1] for r in requests}
    return find_errors(list(requests), resolved, dataset)


def test_the_fixture_requests_are_all_askable(dataset):
    """Nothing on the sample sheet asks for the impossible, so the pane starts empty."""
    resolved = {r.id: resolve_request(r, dataset)[1] for r in dataset.requests}
    assert find_errors(list(dataset.requests), resolved, dataset) == ()
    assert summary(()) == "No errors"


def test_a_request_asking_somebody_for_a_clinic_they_are_not_checked_off_on(dataset):
    (error,) = found(dataset, req("pin", RIFLERY))
    assert error.request == "pin" and error.staff == "dylan"
    assert error.message == "Dylan cannot hold Riflery: not checked off on 'riflery' (Skills sheet)"
    assert summary((error,)) == "1 error(s) in 1 request(s)"


def test_a_request_the_skills_sheet_allows_is_no_error(dataset):
    assert found(dataset, req("fine", ARCHERY)) == ()


def test_a_trainee_is_somebody_who_is_not_checked_off(dataset):
    """Training is the point of a shadow, so asking for one is never this error."""
    trainee = RIFLERY + " AS_ROLE roles.trainee"
    assert found(dataset, req("learn", trainee)) == ()


def test_a_position_the_clinic_does_not_have(dataset):
    (error,) = found(dataset, req("third", ARCHERY + " AS_ROLE roles.third"))
    assert error.message == "Archery 1 & 2 has no third position"


def test_a_clinic_the_day_does_not_run_in_that_block(dataset):
    """The Offerings tab is what the day runs; a block it does not run it in is a mistake."""
    (error,) = found(dataset, req("late", ARCHERY.replace("clinic_1", "clinic_2")))
    assert error.block == "clinic_2" and error.day == TARGET and error.staff == "dylan"
    assert "Archery 1 & 2 is not offered in clinic_2" in error.message
    assert "the day runs it in clinic_1" in error.message


def test_a_clinic_the_day_does_not_run_at_all(dataset):
    (error,) = found(dataset, req("thai", ARCHERY.replace("archery_1_2", "muay_thai")))
    assert "does not run it at all" in error.message


def test_a_choice_the_solver_makes_is_not_an_error(dataset):
    """Who a quantifier picks is the solver's business: it picks somebody who can."""
    anyone = RIFLERY.replace("staff.dylan", "ANY 1 staff.all")
    assert found(dataset, req("any", anyone)) == ()
    somewhere = ARCHERY.replace("blocks.clinic_1", "ANY 1 blocks.all_clinics")
    assert found(dataset, req("loose", somewhere)) == ()


def test_a_quoted_task_asks_for_no_checkoff_and_is_offered_by_nobody(dataset):
    assert (
        found(dataset, req("chore", "REQUEST staff.dylan DO 'paperwork' DURING blocks.clinic_1"))
        == ()
    )


def test_work_asked_of_somebody_who_is_away(dataset):
    """Two requests, one saying he is off and one putting him to work, and one of them is wrong."""
    from dataclasses import replace

    away = replace(
        dataset,
        excluded={dataset.target: {"dylan": {"clinic_1": "offsite", "clinic_2": "offsite"}}},
    )
    (error,) = found(away, req("pin", ARCHERY))
    assert error.staff == "dylan" and error.block == "clinic_1" and error.day == TARGET
    assert error.message == "Dylan is 'offsite' then, so cannot be on Archery 1 & 2"
    # and nothing to say about a block he is back for
    back = found(away, req("later", ARCHERY.replace("clinic_1", "clinic_3")))
    assert [e.message for e in back if "is 'offsite'" in e.message] == []


def test_a_day_that_offers_nothing_is_not_a_day_of_errors(dataset):
    """Before Load offerings there is nothing to be offered in, which is one thing, not fifty."""
    from dataclasses import replace

    bare = replace(dataset, offerings=())
    assert found(bare, req("late", ARCHERY.replace("clinic_1", "clinic_2"))) == ()
