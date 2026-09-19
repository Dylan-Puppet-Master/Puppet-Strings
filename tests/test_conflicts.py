"""Requests that contradict each other, found without solving."""

from datetime import date

import pytest

from puppet_strings.app.conflicts import find_conflicts, summary
from puppet_strings.app.facets import resolve_request
from puppet_strings.model import Priority
from tests.build import request as req

TARGET = date(2026, 9, 16)


def found(dataset, *requests):
    """Every conflict among some requests, with the fixture's own requests left out."""
    resolved = {r.id: resolve_request(r, dataset)[1] for r in requests}
    return find_conflicts(list(requests), resolved, dataset)


PIN = "REQUEST staff.dylan DO activity.riflery DURING block.clinic_1 ON date.target"
FREE = "REQUEST staff.dylan FREE DURING block.clinic_1 ON date.target"


def test_the_fixture_requests_do_not_conflict(dataset):
    """Nothing on the sample sheet contradicts anything else, so the pane starts empty."""
    resolved = {r.id: resolve_request(r, dataset)[1] for r in dataset.requests}
    assert find_conflicts(list(dataset.requests), resolved, dataset) == ()
    assert summary(()) == "No conflicts"


def test_being_asked_to_work_and_to_be_free(dataset):
    (conflict,) = found(dataset, req("pin", PIN), req("free", FREE))
    assert (conflict.staff, conflict.date, conflict.block) == ("dylan", TARGET, "clinic_1")
    assert conflict.reasons == ("must be free, and is asked to do riflery",)
    assert conflict.requests == ("free", "pin")
    assert conflict.where == "dylan · Wed 2026-09-16 · clinic_1"
    assert summary((conflict,)) == "1 conflict(s) over 1 staff member(s)"


def test_the_hard_request_is_named_first(dataset):
    """What must happen is the fixed point, so it heads the list of what is caught."""
    conflicts = found(dataset, req("pin", PIN, Priority.MUST_HAPPEN), req("free", FREE))
    assert conflicts[0].requests == ("pin", "free")


def test_being_asked_to_do_something_and_not_to(dataset):
    off = "REQUEST staff.dylan NOT DO activity.riflery ON date.target"
    (conflict,) = found(dataset, req("pin", PIN), req("off", off))
    assert conflict.reasons == ("must do riflery, and must not do it",)
    assert conflict.block == "clinic_1"  # NOT DO with no DURING reaches every block
    weapons = "REQUEST staff.dylan NOT DO activity.weapons ON date.target"
    (through_category,) = found(dataset, req("pin", PIN), req("off", weapons))
    assert through_category.reasons == ("must do riflery, and must not do it",)


def test_being_asked_to_be_free_and_to_be_busy(dataset):
    busy = "REQUEST staff.dylan NOT FREE DURING block.clinic_1 ON date.target"
    (conflict,) = found(dataset, req("free", FREE), req("busy", busy))
    assert conflict.reasons == ("must be free, and must not be free",)


def test_two_things_that_do_not_fit_in_one_block(dataset):
    """Partial tasks share a block, so this is about minutes, not about being busy."""
    hour = "REQUEST staff.dylan DO 'paperwork' FOR 60m DURING block.clinic_1 ON date.target"
    half = "REQUEST staff.dylan DO 'phone calls' FOR 30m DURING block.clinic_1 ON date.target"
    (conflict,) = found(dataset, req("hour", hour), req("half", half))
    assert "which needs 90 minutes of a 75-minute block" in conflict.reasons[0]
    short = half.replace("30m", "10m")
    assert found(dataset, req("hour", hour), req("short", short)) == ()  # 70 fits in 75


def test_a_clinic_fills_its_block(dataset):
    other = "REQUEST staff.dylan DO activity.archery_1_2 DURING block.clinic_1 ON date.target"
    (conflict,) = found(dataset, req("pin", PIN), req("other", other))
    assert "must do riflery and archery_1_2 at once" in conflict.reasons[0]
    same = "REQUEST staff.dylan DO activity.riflery AS_ROLE role.second DURING block.clinic_1 ON date.target"
    assert found(dataset, req("pin", PIN), req("same", same)) == ()  # the same clinic agrees


def test_a_request_can_contradict_itself(dataset):
    """One block may hold several statements now, so it may hold two that disagree."""
    (conflict,) = found(
        dataset,
        req(
            "muddled",
            "REQUEST staff.dylan DO 'paperwork' FOR 60m DURING block.clinic_1 ON date.target\n"
            "REQUEST staff.dylan FREE DURING block.clinic_1 ON date.target",
        ),
    )
    assert conflict.requests == ("muddled",)
    assert conflict.reasons == ("must be free, and is asked to do paperwork",)


def test_a_choice_the_solver_makes_is_not_a_conflict(dataset):
    """Requests that leave room to move are the solver's business, not the pane's."""
    quiet = [
        # someone, not anyone in particular
        req("any", "REQUEST ANY_1_OF staff.counselor DO activity.riflery DURING block.clinic_1"),
        # somewhere in the day, not in this block
        req("loose", "REQUEST staff.dylan DO 'paperwork' FOR 60m DURING ANY_1_OF block.all"),
        # a preference, which never has to hold
        req("wish", "PREFER AT_MOST 1 staff.dylan DOING activity.riflery"),
    ]
    assert found(dataset, req("free", FREE), *quiet) == ()


def test_each_of_settles_the_matter(dataset):
    """`EACH_OF` names everyone, so it claims each of their blocks."""
    everyone = "REQUEST EACH_OF staff.counselor FREE DURING block.clinic_1 ON date.target"
    conflicts = found(dataset, req("all-free", everyone), req("pin", PIN))
    assert [c.staff for c in conflicts] == ["dylan"]  # the other counselors are asked for nothing


def test_conflicts_are_listed_in_calendar_order(dataset):
    later = PIN.replace("date.target", "2026-09-18")
    free_later = FREE.replace("date.target", "2026-09-18")
    conflicts = found(
        dataset,
        req("pin-later", later),
        req("free-later", free_later),
        req("pin", PIN),
        req("free", FREE),
    )
    assert [c.date for c in conflicts] == [TARGET, date(2026, 9, 18)]


def test_a_date_or_block_that_is_not_there_holds_nothing(dataset):
    """A changeover day has no clinic blocks, so nothing can collide in one."""
    changeover = PIN.replace("date.target", "2026-09-19")
    free_then = FREE.replace("date.target", "2026-09-19")
    assert found(dataset, req("pin", changeover), req("free", free_then)) == ()


@pytest.mark.parametrize(
    "skedge", ["REQUEST staff.nobody DO 'x' DURING block.clinic_1", "nonsense"]
)
def test_an_invalid_request_conflicts_with_nothing(dataset, skedge):
    assert found(dataset, req("bad", skedge), req("free", FREE)) == ()


def test_a_slot_nobody_could_be_assigned_to_is_not_a_conflict(dataset):
    """`Dataset.holds` decides what a slot is, so a block someone rests through is not one."""
    from dataclasses import replace

    resting = replace(dataset, resting={TARGET: {"dylan": frozenset({"clinic_1"})}})
    assert found(dataset, req("pin", PIN), req("free", FREE))  # the same pair, not resting
    assert found(resting, req("pin", PIN), req("free", FREE)) == ()
