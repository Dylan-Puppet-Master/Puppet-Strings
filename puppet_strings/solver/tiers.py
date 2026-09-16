"""Lexicographic solving: one objective per soft tier, each fixed before the next."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import SOFT_TIERS, Priority


@dataclass(frozen=True)
class TierOutcome:
    """The solver after all tiers, or the conflicting assumptions if infeasible."""

    solver: cp_model.CpSolver
    feasible: bool
    conflicts: tuple[int, ...] = ()
    scores: dict[Priority, int] | None = None
    notes: tuple[str, ...] = ()


TIDINESS_SECONDS = 3.0  # cap for each cosmetic pass; a feasible answer is accepted


def solve_tiers(
    model: cp_model.CpModel,
    terms: dict[Priority, list[tuple[int, cp_model.IntVar]]],
    assignments: list[cp_model.IntVar],
    minutes: list,
    config: Config,
) -> TierOutcome:
    """Check feasibility (explaining conflicts), then maximize each tier in order.

    Two final passes keep the schedule tidy: the first minimizes the number of assignments
    so nothing is scheduled that no request asked for; the second minimizes the `minutes`
    expressions (task lengths and offsets from block starts) so partial tasks are as short
    as asked and sit at the start of their block unless a constraint moves them. The
    passes are cosmetic: each stops at TIDINESS_SECONDS and keeps the best found.
    """
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = config.random_seed
    solver.parameters.max_time_in_seconds = config.time_limit_seconds
    solver.parameters.num_workers = 1
    status = solver.Solve(model)
    if status == cp_model.INFEASIBLE:
        return TierOutcome(solver, False, tuple(solver.SufficientAssumptionsForInfeasibility()))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"solver stopped with status {solver.StatusName(status)}")
    solver.parameters.num_workers = config.workers
    scores: dict[Priority, int] = {}
    notes = []
    for tier in SOFT_TIERS:
        if not terms[tier]:
            continue
        expression = sum(coefficient * var for coefficient, var in terms[tier])
        model.Maximize(expression)
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"tier {tier.value}: solver status {solver.StatusName(status)}")
        scores[tier] = round(solver.ObjectiveValue())
        if status == cp_model.FEASIBLE:
            notes.append(f"tier {tier.value} hit the time limit; its score may not be optimal")
        model.ClearObjective()
        model.Add(expression >= scores[tier])
    count = sum(assignments)
    model.Minimize(count)
    solver.parameters.max_time_in_seconds = min(TIDINESS_SECONDS, config.time_limit_seconds)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"final pass: solver status {solver.StatusName(status)}")
    if not minutes:
        return TierOutcome(solver, True, scores=scores, notes=tuple(notes))
    model.ClearObjective()
    model.Add(count <= round(solver.ObjectiveValue()))
    model.Minimize(sum(minutes))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"placement pass: solver status {solver.StatusName(status)}")
    return TierOutcome(solver, True, scores=scores, notes=tuple(notes))
