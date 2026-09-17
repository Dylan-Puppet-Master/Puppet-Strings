"""Passes that run out of time keep the schedule found so far instead of failing."""

import pytest
from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.solver.solve import Cancel, Cancelled, solve
from tests.build import OK, clinic, dataset, request, staff

CONFIG = Config(time_limit_seconds=10, workers=4)
ARCHERY = clinic("Archery 1 & 2", ("Archery 1 & 2", 4), category="weapons")


def build():
    """A day with a clinic to staff and a half-hour break to place inside a block."""
    return dataset(
        [staff("Dylan", archery_1_2=OK), staff("Randy", archery_1_2=OK)],
        [ARCHERY],
        offerings=[("Archery 1 & 2", ["clinic_1"])],
        requests=[
            request(
                "break",
                "REQUEST staff.dylan DO 'break' FOR 30m DURING ANY_1_OF block.any_clinic",
                Priority.MUST_HAPPEN,
            )
        ],
    )


def only_the_first_solve_reports_success(monkeypatch):
    """Every pass after the feasibility check reports UNKNOWN, as a timeout does."""
    real = cp_model.CpSolver.Solve
    calls = []

    def flaky(self, model, *args, **kwargs):
        status = real(self, model, *args, **kwargs)
        calls.append(status)
        return status if len(calls) == 1 else cp_model.UNKNOWN

    monkeypatch.setattr(cp_model.CpSolver, "Solve", flaky)
    return calls


def test_a_schedule_survives_passes_that_find_nothing(monkeypatch):
    calls = only_the_first_solve_reports_success(monkeypatch)
    result = solve(build(), CONFIG)
    assert len(calls) > 3  # the tier passes and both cosmetic passes still ran
    assert result.feasible
    assert [a.staff for a in result.assignments if a.activity == "archery_1_2"]
    assert [a for a in result.assignments if a.activity == "break"]
    assert any("ran out of time" in note for note in result.notes)


def test_an_untimed_solve_reports_no_notes():
    result = solve(build(), CONFIG)
    assert result.feasible and result.notes == ()
    (this_break,) = [a for a in result.assignments if a.activity == "break"]
    assert this_break.minutes == 30


def test_no_schedule_at_all_names_the_setting_to_raise(monkeypatch):
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda self, model, *a, **k: cp_model.UNKNOWN)
    with pytest.raises(RuntimeError, match="raise time_limit_seconds"):
        solve(build(), CONFIG)


class FakeSolver:
    """Records the stop a Cancel sends it, standing in for a search in progress."""

    def __init__(self) -> None:
        self.stopped = False

    def StopSearch(self) -> None:  # noqa: N802 - the name OR-Tools uses
        self.stopped = True


def test_a_cancel_stops_the_running_pass_and_the_ones_after_it():
    cancel = Cancel()
    running = FakeSolver()
    cancel.watch(running)
    assert not running.stopped and not cancel.stopped
    cancel.stop()
    assert running.stopped and cancel.stopped
    later = FakeSolver()
    cancel.watch(later)  # a pass starting after the stop gives up at once
    assert later.stopped
    with pytest.raises(Cancelled):
        cancel.check()


def test_a_stopped_solve_gives_up_instead_of_returning_a_schedule():
    cancel = Cancel()
    cancel.stop()
    with pytest.raises(Cancelled):
        solve(build(), CONFIG, cancel=cancel)


def test_an_unstopped_solve_is_unaffected():
    result = solve(build(), CONFIG, cancel=Cancel())
    assert result.feasible and result.assignments
