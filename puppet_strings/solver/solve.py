"""Solve one target date: build the model from a Dataset and return a Result."""

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.model import Assignment, Dataset, Priority, Request, minute_to_time
from puppet_strings.skedge import ast
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import Count, Requirement, Resolved
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.compile import SCALE, Compiled, Compiler
from puppet_strings.solver.result import Change, RequestOutcome, Result
from puppet_strings.solver.structural import add_structural_constraints
from puppet_strings.solver.tiers import Cancel, Cancelled, solve_tiers
from puppet_strings.solver.variables import Slot, Variables

__all__ = ["Cancel", "Cancelled", "RequestError", "solve"]  # Cancel and Cancelled live in tiers


class RequestError(Exception):
    """A request on the sheet failed validation. Fix it and run again."""

    def __init__(self, request: Request, error: SkedgeError) -> None:
        super().__init__(f"request '{request.id}': {error}")
        self.request = request
        self.error = error


def solve(
    dataset: Dataset,
    config: Config | None = None,
    same_day: bool = False,
    cancel: Cancel | None = None,
) -> Result:
    """Schedule the dataset's target date.

    With `same_day`, the schedule already published for that date is held together: keeping
    it matters more than anything but staffing the clinics, and the result lists what moved.
    Passing a `Cancel` lets another thread stop the solve, which raises `Cancelled`.
    """
    config = config or Config()
    cancel = cancel or Cancel()
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
    _check_adhoc_tasks(copies)
    compiler.prepare(copies)
    active = set()
    for request, copy in copies:
        cancel.check()  # building the model is the part that holds the interpreter
        if compiler.compile(request, copy):
            active.add(request.id)
    compiler.close()
    variables.finish()
    add_structural_constraints(model, variables, dataset)
    baseline = dataset.baseline if same_day else None
    if baseline is not None:
        _hold_to(model, compiler, variables, baseline)

    for compiled in compiler.compiled:  # start from "every request is met" and repair
        if isinstance(compiled.sat, cp_model.IntVar):
            model.AddHint(compiled.sat, 1)

    unique = {var.Index(): var for var in variables.x.values()}
    placement = [
        iv.start - iv.block.start_minute for iv in variables.intervals.values() if iv.partial
    ]
    outcome = solve_tiers(model, compiler.terms, list(unique.values()), placement, config, cancel)
    if not outcome.feasible:
        conflicts = tuple(
            compiler.compiled[i].id
            for i in _assumption_positions(outcome.conflicts, compiler.compiled)
        )
        return Result(feasible=False, conflicts=conflicts)
    missed = [c for c in compiler.compiled if not _true(outcome, c.sat)]
    deferred = [
        c for c in compiler.compiled if _true(outcome, c.sat) and _true(outcome, c.deferred)
    ]
    assignments = _assignments(outcome, variables, dataset)
    return Result(
        feasible=True,
        assignments=assignments,
        unsatisfied=tuple(_outcome(c) for c in missed),
        deferred=tuple(_outcome(c) for c in deferred),
        inactive=tuple(
            RequestOutcome(r.id, r.priority, r.description)
            for r in dataset.requests
            if r.id not in active
        ),
        notes=outcome.notes,
        changes=_changes(baseline, assignments),
        tier_scores=outcome.scores or {},
    )


def _check_adhoc_tasks(copies: list[tuple[Request, Resolved]]) -> None:
    """A quoted task means nothing unless some positive REQUEST asks for it.

    A `REQUEST … DO` asks for it, and so does a `REQUEST AT_LEAST` or `EXACTLY` pattern.
    """
    asked = {_task(st) for _, copy in copies for st in copy.statements if _asks(st)}
    for request, copy in copies:
        for st in copy.statements:
            text = _task(st)
            if text is None or text in asked or _asks(st):
                continue
            raise RequestError(
                request,
                SkedgeError(f"no request asks for '{text}'", st.pos.line, st.pos.column),
            )


def _task(statement) -> str | None:
    what = statement.what if isinstance(statement, Requirement) else statement.pattern.what
    return what.text if isinstance(what, ast.Task) else None


def _asks(statement) -> bool:
    if isinstance(statement, Requirement):
        return True
    return (
        isinstance(statement, Count)
        and not statement.prefer
        and statement.amount.bound != ast.AT_MOST
    )


def _hold_to(model, compiler: Compiler, variables: Variables, baseline) -> None:
    """Reward every published assignment the day can still keep, and start the solver there."""
    hinted = set()
    for a in baseline:
        var = variables.x.get(Slot(a.staff, a.activity, a.role, a.block))
        if var is None:
            continue  # nobody can hold it today, so there is nothing to keep
        compiler.terms[Priority.STABILITY].append((SCALE, var))
        if var.Index() not in hinted:  # one hint per variable, not per block of a (DBL)
            hinted.add(var.Index())
            model.AddHint(var, 1)


def _changes(baseline, assignments: tuple[Assignment, ...]) -> tuple[Change, ...]:
    """What each staff member's block held before and after, where the two differ."""
    if baseline is None:
        return ()
    before, after = _by_staff_block(baseline), _by_staff_block(assignments)
    changes = []
    for key in sorted(set(before) | set(after)):
        was, now = before.get(key, ()), after.get(key, ())
        if [_shape(a) for a in was] != [_shape(a) for a in now]:
            changes.append(Change(key[0], key[1], was, now))
    return tuple(changes)


def _by_staff_block(assignments) -> dict[tuple[str, str], tuple[Assignment, ...]]:
    grouped: dict[tuple[str, str], list[Assignment]] = {}
    for a in assignments:
        grouped.setdefault((a.staff, a.block), []).append(a)
    return {key: tuple(sorted(rows, key=_shape)) for key, rows in grouped.items()}


def _shape(a: Assignment) -> tuple:
    return (a.start, a.activity, a.role or "", a.minutes)


def _assumption_positions(conflicts: tuple[int, ...], compiled: list[Compiled]) -> list[int]:
    by_index = {c.sat.Index(): i for i, c in enumerate(compiled) if c.request.priority.hard}
    return sorted(by_index[index] for index in conflicts if index in by_index)


def _assignments(outcome, variables: Variables, dataset: Dataset) -> tuple[Assignment, ...]:
    assignments = []
    for slot, var in variables.x.items():
        if not outcome.value(var):
            continue
        interval = variables.intervals[slot]
        assignments.append(
            Assignment(
                staff=slot.staff,
                activity=slot.activity,
                role=slot.role,
                date=dataset.target,
                block=slot.block,
                start=minute_to_time(_value(outcome, interval.start)),
                minutes=_value(outcome, interval.size),
                source=variables.sources[slot],
            )
        )
    return tuple(assignments)


def _value(outcome, value) -> int:
    """A start or size: a constant for a whole block, a variable for part of one."""
    return value if isinstance(value, int) else outcome.value(value)


def _true(outcome, literal) -> bool:
    if isinstance(literal, bool):
        return literal
    if isinstance(literal, cp_model.IntVar):
        return bool(outcome.value(literal))
    return not outcome.value(literal.Not())


def _outcome(compiled: Compiled) -> RequestOutcome:
    return RequestOutcome(compiled.id, compiled.request.priority, compiled.request.description)
