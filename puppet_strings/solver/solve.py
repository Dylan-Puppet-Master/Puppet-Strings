"""Solve one target date: build the model from a Dataset and return a Result."""

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from puppet_strings.config import Config
from puppet_strings.exclude import apply_exclusions
from puppet_strings.model import Assignment, Dataset, Priority, Request, minute_to_time
from puppet_strings.skedge import ast
from puppet_strings.skedge.ast import NoSession, SkedgeError
from puppet_strings.skedge.resolve import Exclusion, Requirement, Resolved, asks
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.compile import SCALE, Compiled, Compiler
from puppet_strings.solver.result import Change, RequestOutcome, Result
from puppet_strings.solver.structural import add_structural_constraints
from puppet_strings.solver.tiers import Cancel, Cancelled, solve_tiers
from puppet_strings.solver.variables import Slot, Variables

# Cancel and Cancelled live in tiers
__all__ = ["Cancel", "Cancelled", "Resolutions", "build_model", "solve"]


@dataclass(frozen=True)
class Resolutions:
    """Requests already resolved, and the dataset they were resolved against.

    The request manager resolves every request when it loads a day, to list and check
    them; handing those copies to the solve spares it doing the same work again.
    """

    dataset: Dataset
    copies: dict[str, tuple[Request, tuple[Resolved, ...]]] = field(default_factory=dict)


# What resolving a request reads. The past days a solve adds are not among them.
RESOLVED_AGAINST = (
    "target",
    "staff",
    "staff_categories",
    "activities",
    "activity_categories",
    "blocks",
    "block_categories",
    "calendar",
    "spans",
    "mappings",
)


def solve(
    dataset: Dataset,
    config: Config | None = None,
    same_day: bool = False,
    cancel: Cancel | None = None,
    known: Resolutions | None = None,
) -> Result:
    """Schedule the dataset's target date.

    With `same_day`, the schedule already published for that date is held together: keeping
    it matters more than anything but staffing the clinics, and the result lists what moved.
    Passing a `Cancel` lets another thread stop the solve, which raises `Cancelled`.
    A request that does not validate is left out, and the result's notes say so: the
    requests file may hold one half written, and the day is still to be solved.
    `known` are copies already resolved, used for each request that is still as it was
    when they were made, against names that are still the same.

    `tier_seconds_limit` is the budget each pass gets, so how long a solve takes depends on
    how many tiers the requests use as well as on the setting.
    """
    config = config or Config()
    cancel = cancel or Cancel()
    # Who an EXCLUDE takes out of the day comes out of it before a variable is made. A load
    # has already done this; doing it again costs a substring search per request and means
    # a solve is right about who is here however its dataset was put together.
    dataset = apply_exclusions(dataset)
    reuse = known.copies if known is not None and _same_names(known.dataset, dataset) else {}
    copies = []
    left_out: dict[str, str] = {}  # request id -> why
    for request in dataset.requests:
        cached = reuse.get(request.id)
        if cached is not None and cached[0] == request and cached[1]:
            copies += [(request, copy) for copy in cached[1]]
            continue  # an invalid one resolved to nothing, so it is still checked below
        try:
            resolved = validate_request(request, dataset)
        except NoSession:
            continue  # about the session being scheduled, and this date is in none
        except SkedgeError as e:
            left_out[request.id] = str(e)
            continue
        copies += [(request, copy) for copy in resolved]
    left_out |= _unasked_tasks(copies)
    copies = [(r, copy) for r, copy in copies if r.id not in left_out]
    notes = tuple(f"Left out {i}, which does not validate: {why}" for i, why in left_out.items())
    model, variables, compiler, active = build_model(dataset, copies, cancel)
    baseline = dataset.baseline if same_day else None
    hints: dict[int, tuple[cp_model.IntVar, int]] = {}
    if baseline is not None:
        _hold_to(compiler, variables, baseline, hints)
    for compiled in compiler.compiled:  # start from "every request is met" and repair
        _hint(hints, compiled.sat)
    for var, value in hints.values():
        model.AddHint(var, value)

    placement = [
        iv.start - iv.block.start_minute for iv in variables.intervals.values() if iv.partial
    ]
    outcome = solve_tiers(model, compiler.terms, placement, config, cancel)
    if not outcome.feasible:
        conflicts = tuple(
            compiler.compiled[i].id
            for i in _assumption_positions(outcome.conflicts, compiler.compiled)
        )
        return Result(feasible=False, conflicts=conflicts, notes=notes)
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
            if r.id not in active and r.id not in left_out
        ),
        notes=notes + outcome.notes,
        changes=_changes(baseline, assignments),
        tier_scores=outcome.scores or {},
    )


def build_model(dataset: Dataset, copies: list[tuple[Request, Resolved]], cancel=None):
    """The model for these request copies, its variables and compiler, and what is active.

    The last is the ids of the requests active on the target date. Everything a solve adds
    on top -- holding to a published day, the hints, the tiers -- is left to the caller, so
    anything else that needs the solver's own model of some requests builds it the same way.
    """
    cancel = cancel or Cancel()
    model = cp_model.CpModel()
    variables = Variables(model, dataset)
    compiler = Compiler(model, variables, dataset)
    compiler.prepare(copies)
    active = set()
    for request, copy in copies:
        cancel.check()  # building the model is the part that holds the interpreter
        if compiler.compile(request, copy):
            active.add(request.id)
    compiler.close()
    variables.finish()
    add_structural_constraints(model, variables, dataset)
    return model, variables, compiler, active


def _same_names(a: Dataset, b: Dataset) -> bool:
    """Whether a request resolves the same against both: every name means the same."""
    return a is b or all(getattr(a, f) == getattr(b, f) for f in RESOLVED_AGAINST)


def _unasked_tasks(copies: list[tuple[Request, Resolved]]) -> dict[str, str]:
    """The requests about a quoted task nobody asks for, by id, with why: to be left out.

    A quoted task means nothing unless some positive REQUEST asks for it. A `REQUEST … DO`
    asks for it, unless all it says is how much there may be at most.
    """
    asked = {_task(st) for _, copy in copies for st in copy.statements if asks(st)}
    unasked: dict[str, str] = {}
    for request, copy in copies:
        for st in copy.statements:
            text = _task(st)
            if text is None or text in asked or asks(st) or request.id in unasked:
                continue
            error = SkedgeError(f"no request asks for '{text}'", st.pos.line, st.pos.column)
            unasked[request.id] = str(error)
    return unasked


def _task(statement) -> str | None:
    """The quoted task a statement is about, if it is about one.

    An `EXCLUDE`'s quoted word is a label for the schedule rather than a task anybody does,
    so it asks for nothing and needs nobody to ask for it.
    """
    if isinstance(statement, Exclusion):
        return None
    what = statement.what if isinstance(statement, Requirement) else statement.pattern.what
    return what.text if isinstance(what, ast.Task) else None


def _hold_to(compiler: Compiler, variables: Variables, baseline, hints: dict) -> None:
    """Reward every published assignment the day can still keep, and start the solver there."""
    for a in baseline:
        var = variables.x.get(Slot(a.staff, a.activity, a.role, a.block))
        if var is None:
            continue  # nobody can hold it today, so there is nothing to keep
        compiler.terms[Priority.STABILITY].append((SCALE, var))
        _hint(hints, var)


def _hint(hints: dict, literal) -> None:
    """Hint a literal true, once per variable: CP-SAT rejects a model that hints one twice.

    Two copies can be met by the same literal (`Compiler._collapse`), a (DBL) holds one
    variable in two blocks, and a copy may be met by a negated literal. The first hint for a
    variable stands, so a published assignment the day is holding to outranks a request.
    """
    if isinstance(literal, bool):
        return
    if isinstance(literal, cp_model.IntVar):
        hints.setdefault(literal.Index(), (literal, 1))
    else:
        hints.setdefault(literal.Not().Index(), (literal.Not(), 0))


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
