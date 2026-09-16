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


def solve_tiers(
    model: cp_model.CpModel,
    terms: dict[Priority, list[tuple[int, cp_model.IntVar]]],
    assignments: list[cp_model.IntVar],
    config: Config,
) -> TierOutcome:
    """Check feasibility (explaining conflicts), then maximize each tier in order.

    A last pass minimizes the number of assignments, so nothing is scheduled that no
    request asked for.
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
    model.Minimize(sum(assignments))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"final pass: solver status {solver.StatusName(status)}")
    return TierOutcome(solver, True, scores=scores, notes=tuple(notes))
