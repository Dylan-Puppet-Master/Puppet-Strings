"""Solve one target date: build the model from a Dataset and return a Result."""

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import Assignment, Dataset, Request, minute_to_time
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.compile import Compiled, Compiler
from puppet_strings.solver.result import RequestOutcome, Result
from puppet_strings.solver.structural import add_structural_constraints
from puppet_strings.solver.tiers import solve_tiers
from puppet_strings.solver.variables import Variables


class RequestError(Exception):
    """A request on the sheet failed validation. Fix it and run again."""

    def __init__(self, request: Request, error: SkedgeError) -> None:
        super().__init__(f"request '{request.id}': {error}")
        self.request = request
        self.error = error


def solve(dataset: Dataset, config: Config | None = None) -> Result:
    """Schedule the dataset's target date."""
    config = config or Config()
    model = cp_model.CpModel()
    variables = Variables(model, dataset)
    compiler = Compiler(model, variables, dataset)
    copies = []
    for request in dataset.requests:
        try:
            resolved = validate_request(request, dataset)
        except SkedgeError as e:
            raise RequestError(request, e) from e
        copies += [(request, copy) for copy in resolved]
    compiler.prepare(copies)
    copies.sort(key=lambda pair: not any(s.verb == "TASK" for s in pair[1].statements))
    for request, copy in copies:
        compiler.compile(request, copy)
    variables.finish()
    add_structural_constraints(model, variables, dataset)

    unique = {var.Index(): var for var in variables.x.values()}
    minutes = [
        expr
        for iv in variables.intervals.values()
        if iv.partial
        for expr in (iv.size, iv.start - iv.block.start_minute)
    ]
    outcome = solve_tiers(model, compiler.terms, list(unique.values()), minutes, config)
    if not outcome.feasible:
        conflicts = tuple(
            compiler.compiled[i].id
            for i in _assumption_positions(outcome.conflicts, compiler.compiled)
        )
        return Result(feasible=False, conflicts=conflicts)
    solver = outcome.solver
    return Result(
        feasible=True,
        assignments=_assignments(solver, variables, dataset),
        unsatisfied=tuple(
            _outcome(c) for c in compiler.compiled if not c.deferrable and not solver.Value(c.sat)
        ),
        deferred=tuple(
            _outcome(c) for c in compiler.compiled if c.deferrable and not solver.Value(c.sat)
        ),
        notes=outcome.notes,
        tier_scores=outcome.scores or {},
    )


def _assumption_positions(conflicts: tuple[int, ...], compiled: list[Compiled]) -> list[int]:
    by_index = {c.sat.Index(): i for i, c in enumerate(compiled)}
    return sorted(by_index[index] for index in conflicts if index in by_index)


def _assignments(solver, variables: Variables, dataset: Dataset) -> tuple[Assignment, ...]:
    assignments = []
    for slot, var in variables.x.items():
        if not solver.Value(var):
            continue
        interval = variables.intervals[slot]
        assignments.append(
            Assignment(
                staff=slot.staff,
                activity=slot.activity,
                role=slot.role,
                date=dataset.target,
                block=slot.block,
                start=minute_to_time(_value(solver, interval.start)),
                minutes=_value(solver, interval.size),
                source=variables.sources[slot],
            )
        )
    return tuple(assignments)


def _value(solver, value) -> int:
    return value if isinstance(value, int) else solver.Value(value)


def _outcome(compiled: Compiled) -> RequestOutcome:
    return RequestOutcome(compiled.id, compiled.request.priority, compiled.request.description)
