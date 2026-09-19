"""Lexicographic solving: one objective per soft tier, each fixed before the next.

Every pass after the first starts from a schedule that already works, so a pass that runs
out of time keeps that schedule and adds a note rather than failing the solve.

`time_limit_seconds` is the budget for the whole solve, not for each pass: one clock runs
from the moment the solve starts, and every pass gets what is left of it. The cosmetic
placement pass is the exception, in that `tidy_seconds` of the budget is held back for it,
so a slow tier cannot leave the day's partial tasks sitting wherever they happened to land.
"""

import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import SOFT_TIERS, Priority
from puppet_strings.solver.compile import SCALE


class Cancelled(Exception):
    """The solve was stopped before it finished."""


class Cancel:
    """Stops a solve from another thread, between passes and inside the one running.

    A solve holds the interpreter for much of the time it spends building the model, so a
    caller waiting on it cannot poll. It hands one of these in instead and calls `stop`.
    """

    def __init__(self) -> None:
        self._stopped = False
        self._solver: cp_model.CpSolver | None = None

    @property
    def stopped(self) -> bool:
        """Whether a stop has been asked for."""
        return self._stopped

    def stop(self) -> None:
        """Ask the solve to stop. Safe to call from another thread."""
        self._stopped = True
        if self._solver is not None:
            self._solver.StopSearch()

    def watch(self, solver: cp_model.CpSolver) -> None:
        """Let `stop` reach the solver that is about to search."""
        self._solver = solver
        if self._stopped:
            solver.StopSearch()

    def check(self) -> None:
        """Give up if the solve has been stopped."""
        if self._stopped:
            raise Cancelled


@dataclass
class Deadline:
    """The solve's one clock. `seconds` is the whole budget; it starts running at once."""

    seconds: float
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        """How much of the budget is left, never below zero."""
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def give(self, solver: cp_model.CpSolver, holding_back: float = 0.0) -> float:
        """Hand the solver what is left, less anything held back. Returns what it got."""
        seconds = max(0.0, self.remaining - holding_back)
        solver.parameters.max_time_in_seconds = seconds
        return seconds


@dataclass(frozen=True)
class TierOutcome:
    """The schedule the solver settled on, or the conflicting assumptions if infeasible."""

    feasible: bool
    values: tuple[int, ...] = ()
    conflicts: tuple[int, ...] = ()
    scores: dict[Priority, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def value(self, var: cp_model.IntVar) -> int:
        """What this variable holds in the schedule."""
        return self.values[var.Index()]


def solve_tiers(
    model: cp_model.CpModel,
    terms: dict[Priority, list[tuple[int, cp_model.IntVar]]],
    assignments: list[cp_model.IntVar],
    placement: list,
    config: Config,
    cancel: Cancel,
    deadline: Deadline | None = None,
) -> TierOutcome:
    """Check feasibility (explaining conflicts), then maximize each tier in order.

    A cosmetic pass follows, minimizing the `placement` expressions (offsets from block
    starts) so that a task shorter than its block sits at the start of it unless a
    constraint moves it. It starts from the schedule already found, so `tidy_seconds` of
    the budget is enough for it: the improvement turns up at once, and only proving it
    optimal takes long.

    `deadline` is the solve's clock, which the caller starts before building the model, so
    that building counts against the budget like everything else.
    """
    deadline = deadline or Deadline(config.time_limit_seconds)
    tidy = min(config.tidy_seconds, config.time_limit_seconds) if placement else 0.0
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = config.random_seed
    deadline.give(solver, holding_back=tidy)
    solver.parameters.num_workers = 1
    cancel.watch(solver)
    status = solver.Solve(model)
    cancel.check()
    if status == cp_model.INFEASIBLE:
        return TierOutcome(False, conflicts=tuple(solver.SufficientAssumptionsForInfeasibility()))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"no schedule found within the {config.time_limit_seconds:.0f}s budget, which "
            "covers building the model as well as solving; raise time_limit_seconds in "
            "config.toml"
        )
    values = _snapshot(solver)
    solver.parameters.num_workers = config.workers
    scores: dict[Priority, int] = {}
    notes: list[str] = []

    for tier in SOFT_TIERS:
        if not terms[tier]:
            continue
        expression = sum(coefficient * var for coefficient, var in terms[tier])
        if deadline.give(solver, holding_back=tidy) <= 0:
            scores[tier] = _total(terms[tier], values)
            notes.append(
                f"tier {tier.value}: the {config.time_limit_seconds:.0f}s budget was spent "
                "before this tier ran; kept the schedule from the tier before"
            )
            model.Add(expression >= scores[tier])
            continue
        model.Maximize(expression)
        status = solver.Solve(model)
        cancel.check()
        model.ClearObjective()
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            values = _snapshot(solver)
            scores[tier] = round(solver.ObjectiveValue())
            if status == cp_model.FEASIBLE:
                notes.append(_unproven(tier, scores[tier], solver.BestObjectiveBound(), config))
        else:
            scores[tier] = _total(terms[tier], values)
            notes.append(
                f"tier {tier.value}: ran out of the {config.time_limit_seconds:.0f}s budget "
                "without a schedule of its own; kept the one from the tier before, which "
                "still holds every request met so far"
            )
        model.Add(expression >= scores[tier])

    if placement:
        # what was held back for it, or whatever is left if a tier overran its allowance
        seconds = min(tidy, deadline.remaining)
        values, placed = _minimize(model, solver, sum(placement), values, assignments, seconds)
        cancel.check()
        if not placed:
            notes.append("placement pass ran out of time; partial tasks may sit later in a block")
    return TierOutcome(True, values, scores=scores, notes=tuple(notes))


def _unproven(tier: Priority, score: int, bound: float, config: Config) -> str:
    """Why a tier stopped: it has a schedule, it just could not prove none is better.

    The schedule is kept either way, so what is worth saying is how much room is left: the
    solver ruled out everything above `bound`, and the gap to the score is what it could
    not rule out. A request of weight 1 is worth `SCALE`, so the gap reads in requests,
    which is the size the Puppet Master thinks in. A gap under a tenth of a request is
    rounding and says so.
    """
    limit = f"{config.time_limit_seconds:.0f}s"
    head = (
        f"tier {tier.value}: could not prove this schedule optimal within the solve's "
        f"{limit}; it is kept"
    )
    if bound in (float("inf"), float("-inf")) or bound < score:
        return f"{head}, and nothing better was ruled out"
    gap = (bound - score) / SCALE
    if gap < 0.1:
        return f"{head}, and it is within a rounding error of the best possible"
    return (
        f"{head}. It scores {score / SCALE:.1f} and the best possible is somewhere up to "
        f"{bound / SCALE:.1f}, so at most {gap:.1f} more requests' worth was on the table. "
        f"Raise time_limit_seconds to let it finish the proof"
    )


def _minimize(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    expression,
    values: tuple[int, ...],
    hints: list[cp_model.IntVar],
    seconds: float,
) -> tuple[tuple[int, ...], bool]:
    """Minimize an expression, keeping the current schedule if the pass finds nothing."""
    model.ClearHints()
    for var in hints:
        model.AddHint(var, values[var.Index()])
    model.Minimize(expression)
    solver.parameters.max_time_in_seconds = seconds
    status = solver.Solve(model)
    model.ClearObjective()
    model.ClearHints()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _snapshot(solver), True
    return values, False


def _snapshot(solver: cp_model.CpSolver) -> tuple[int, ...]:
    """Every variable's value in the solution, by variable index."""
    return tuple(solver.ResponseProto().solution)


def _total(terms: list[tuple[int, cp_model.IntVar]], values: tuple[int, ...]) -> int:
    return sum(coefficient * values[var.Index()] for coefficient, var in terms)
