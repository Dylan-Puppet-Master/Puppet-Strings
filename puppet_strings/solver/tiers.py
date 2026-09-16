"""Lexicographic solving: one objective per soft tier, each fixed before the next.

Every pass after the first starts from a schedule that already works, so a pass that runs
out of time keeps that schedule and adds a note rather than failing the solve.
"""

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import SOFT_TIERS, Priority


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
    minutes: list,
    config: Config,
) -> TierOutcome:
    """Check feasibility (explaining conflicts), then maximize each tier in order.

    Two cosmetic passes follow: the first minimizes the number of assignments, so nothing
    is scheduled that no request asked for; the second minimizes the `minutes` expressions
    (task lengths and offsets from block starts), so partial tasks are as short as asked
    and sit at the start of their block unless a constraint moves them. Both start from
    the schedule already found, so they get `tidy_seconds` rather than the tier limit:
    the improvement turns up at once, and only proving it optimal takes long.
    """
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = config.random_seed
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    solver.parameters.num_workers = 1
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        return TierOutcome(False, conflicts=tuple(solver.SufficientAssumptionsForInfeasibility()))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"no schedule found within {config.time_limit_seconds:.0f}s; "
            "raise time_limit_seconds in config.toml"
        )
    values = _snapshot(solver)
    solver.parameters.num_workers = config.workers
    scores: dict[Priority, int] = {}
    notes: list[str] = []

    for tier in SOFT_TIERS:
        if not terms[tier]:
            continue
        expression = sum(coefficient * var for coefficient, var in terms[tier])
        model.Maximize(expression)
        status = solver.Solve(model)
        model.ClearObjective()
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            values = _snapshot(solver)
            scores[tier] = round(solver.ObjectiveValue())
            if status == cp_model.FEASIBLE:
                notes.append(f"tier {tier.value} hit the time limit; its score may not be optimal")
        else:
            scores[tier] = _total(terms[tier], values)
            notes.append(f"tier {tier.value} ran out of time; kept the schedule so far")
        model.Add(expression >= scores[tier])

    seconds = min(config.tidy_seconds, config.time_limit_seconds)
    count = sum(assignments)
    values, tidied = _minimize(model, solver, count, values, assignments, seconds)
    if tidied:
        model.Add(count <= _total([(1, var) for var in assignments], values))
    else:
        notes.append("tidying pass ran out of time; the schedule may hold extra assignments")
    if minutes:
        values, placed = _minimize(model, solver, sum(minutes), values, assignments, seconds)
        if not placed:
            notes.append("placement pass ran out of time; partial tasks may sit later in a block")
    return TierOutcome(True, values, scores=scores, notes=tuple(notes))


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
