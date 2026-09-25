"""Passes that run out of time keep the schedule found so far instead of failing."""

import pytest
from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.solver.solve import Cancel, Cancelled, solve
from tests.build import OK, clinic, dataset, request, staff

CONFIG = Config(tier_seconds_limit=10, workers=4)
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
                "REQUEST staff.dylan DO 'break' FOR EXACTLY 30m DURING ANY 1 blocks.all_clinics",
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
    assert len(calls) > 2  # the tier pass and the placement pass still ran after the first
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
    with pytest.raises(RuntimeError, match="raise tier_seconds_limit"):
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


# -- what a tier says when the clock beats it ------------------------------------------------


def unproven(score, bound, seconds=30):
    from puppet_strings.solver.tiers import _unproven

    return _unproven(Priority.MEDIUM, score, bound, Config(tier_seconds_limit=seconds))


def test_an_unproven_tier_says_how_much_was_left_on_the_table():
    note = unproven(42000, 48500.0)
    assert note.startswith(
        "tier MEDIUM: could not prove this schedule optimal within its 30s; it is kept"
    )
    assert "It scores 42.0" in note and "somewhere up to 48.5" in note
    assert "at most 6.5 more requests' worth" in note
    assert "Raise tier_seconds_limit" in note


def test_a_tier_that_is_all_but_proven_says_so_instead_of_a_number():
    assert "within a rounding error" in unproven(42000, 42050.0)


def test_a_tier_that_ruled_nothing_out_does_not_invent_a_gap():
    assert "nothing better was ruled out" in unproven(42000, float("inf"))
    assert "nothing better was ruled out" in unproven(42000, 41000.0)  # a bound below the score


def test_a_timed_out_tier_carries_that_note(monkeypatch):
    """The whole solve, to check the note reaches the report rather than just reading well."""
    real = cp_model.CpSolver.Solve
    calls = []

    def feasible_but_unproven(self, model, *args, **kwargs):
        status = real(self, model, *args, **kwargs)
        calls.append(status)
        return cp_model.FEASIBLE if len(calls) > 1 else status

    monkeypatch.setattr(cp_model.CpSolver, "Solve", feasible_but_unproven)
    result = solve(build(), CONFIG)
    assert result.feasible
    assert any("could not prove this schedule optimal" in note for note in result.notes)


def test_the_budget_is_for_each_pass_not_the_whole_solve(monkeypatch):
    """Every pass starts with the whole setting, so a slow one costs the others nothing."""
    asked = []
    real = cp_model.CpSolver.Solve

    def note_the_limit(self, model, *args, **kwargs):
        asked.append(self.parameters.max_time_in_seconds)
        return real(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", note_the_limit)
    result = solve(build(), Config(tier_seconds_limit=10, tidy_seconds=5, workers=4))
    assert result.feasible
    assert len(asked) > 2
    assert all(limit == 10 for limit in asked[:-1])  # the feasibility pass and every tier
    assert asked[-1] == 5  # the placement pass gets tidy_seconds


def test_every_pass_after_the_first_starts_from_the_schedule_before_it(monkeypatch):
    """With the tiers before it held at their best, a late tier may not find a schedule
    from nothing in the time it has left, so it is handed the last one whole."""
    seen = []
    real = cp_model.CpSolver.Solve

    def note_the_hint(self, model, *args, **kwargs):
        proto = model.Proto()
        hint = dict(zip(proto.solution_hint.vars, proto.solution_hint.values, strict=True))
        status = real(self, model, *args, **kwargs)
        seen.append((hint, len(proto.variables), tuple(self.ResponseProto().solution)))
        return status

    monkeypatch.setattr(cp_model.CpSolver, "Solve", note_the_hint)
    assert solve(build(), CONFIG).feasible
    assert len(seen) > 2
    for (_, _, before), (hint, count, _) in zip(seen, seen[1:], strict=False):
        assert len(hint) == count  # every variable, not just the assignments
        assert tuple(hint[i] for i in range(count)) == before
