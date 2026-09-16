"""Every check a request must pass before the solver sees it."""

from puppet_strings.model import Dataset, Request
from puppet_strings.sheets.metrics import KEY_FIELDS
from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Resolved, resolve
from puppet_strings.skedge.scope import ScopedDeclaration, ScopedVerb, scope


def validate_request(request: Request, dataset: Dataset) -> tuple[Resolved, ...]:
    """Parse, check, and resolve one request. Raises SkedgeError with line and column."""
    if request.weight <= 0:
        raise ast.SkedgeError("weight must be positive", 1, 1)
    if request.priority.hard and request.weight != 1:
        raise ast.SkedgeError("weight is not allowed with MUST_HAPPEN", 1, 1)
    scoped = scope(parse(request.skedge))
    check(scoped, hard=request.priority.hard)
    return resolve(scoped, dataset)


def check(scoped: ScopedDeclaration, hard: bool) -> None:
    """Rules about which clauses go with which verbs, and GAP labels."""
    labels: dict[str, ScopedVerb] = {}
    for verb in scoped.verbs:
        _check_verb(verb, hard)
        label = verb.get(ast.Label)
        if label is None:
            continue
        if label.name in labels:
            raise _error(f"label '{label.name}' defined twice", label)
        labels[label.name] = verb
    for gap in scoped.gaps:
        for name in (gap.first, gap.second):
            if name not in labels:
                raise _error(f"undefined label '{name}'", gap)
            _check_gap_task(labels[name], gap)


def _check_verb(scoped: ScopedVerb, hard: bool) -> None:
    verb = scoped.verb
    kind = verb.kind
    if scoped.get(ast.During) is None:
        raise _error(f"{kind} needs DURING", verb)
    if kind in ("PREFER", "AVOID") and hard:
        raise _error(f"{kind} cannot be MUST_HAPPEN", verb)
    if isinstance(verb.target, ast.Free) and kind == "FORBID":
        raise _error("FORBID FREE is not allowed; use TASK", verb)
    if scoped.get(ast.Role) and not isinstance(verb.target, ast.Selector):
        raise _error("ROLE needs an activity target", scoped.get(ast.Role))
    if (label := scoped.get(ast.Label)) and kind != "TASK":
        raise _error("AS is only for TASK", label)
    if (for_ := scoped.get(ast.For)) is not None:
        if kind != "TASK":
            raise _error("FOR is only for TASK", for_)
        if _quantifier(scoped.get(ast.During).selector) == "ALL":
            raise _error("FOR cannot combine with DURING ALL", for_)
    metric = scoped.get(ast.MetricClause)
    per = scoped.get(ast.Per)
    if metric and kind not in ("PREFER", "AVOID"):
        raise _error("~ is only for PREFER and AVOID", metric)
    if metric and per:
        raise _error("~ cannot combine with PER", metric)
    if per:
        if kind != "AVOID":
            raise _error("PER ... BEYOND is only for AVOID", per)
        if per.beyond < 1:
            raise _error("BEYOND must be at least 1", per)
        bad = [f for f in per.fields if f not in KEY_FIELDS]
        if bad:
            raise _error(f"PER fields must be some of {', '.join(KEY_FIELDS)}", per)
    if kind != "TASK":
        for clause, selector in _selectors(scoped):
            if _quantifier(selector) not in (None, "ANY"):
                raise ast.SkedgeError(
                    f"{kind} takes no quantifier; it filters assignments",
                    selector.pos.line,
                    selector.pos.column,
                )
            if clause != "ACROSS" and _has_and(selector.expr):
                raise ast.SkedgeError(
                    f"{kind}: AND belongs in ACROSS, where it means staff working together",
                    selector.pos.line,
                    selector.pos.column,
                )


def _check_gap_task(scoped: ScopedVerb, gap: ast.Gap) -> None:
    during = scoped.get(ast.During).selector
    if _quantifier(during) in ("ALL", "OF") or _has_and(during.expr):
        raise _error("GAP tasks must occupy a single block (no ALL, OF, or AND)", gap)


def _selectors(scoped: ScopedVerb):
    """(clause name, selector) for every selector the verb uses."""
    if isinstance(scoped.verb.target, ast.Selector):
        yield scoped.verb.kind, scoped.verb.target
    for name, kind in (
        ("ON", ast.On),
        ("DURING", ast.During),
        ("ACROSS", ast.Across),
        ("ROLE", ast.Role),
    ):
        clause = scoped.get(kind)
        if clause is not None:
            yield name, clause.selector


def _quantifier(selector: ast.Selector) -> str | None:
    return selector.quantifier.kind if selector.quantifier else None


def _has_and(expr: ast.Expr) -> bool:
    if isinstance(expr, ast.And):
        return True
    if isinstance(expr, ast.Or):
        return any(_has_and(item) for item in expr.items)
    return False


def _error(message: str, clause: ast.Clause) -> ast.SkedgeError:
    return ast.SkedgeError(message, clause.pos.line, clause.pos.column)
