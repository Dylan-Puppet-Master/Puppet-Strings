"""Turn scoped verbs into statements over concrete items from a Dataset.

Selectors become Choices: the items involved and how they combine. `EACH` is expanded
here into independent copies of the declaration.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import product

from puppet_strings.model import (
    LIFEGUARD_ROLES,
    ORDINALS,
    POSITION_ROLES,
    TRAINEE_ROLES,
    Dataset,
)
from puppet_strings.skedge import ast
from puppet_strings.skedge.scope import ScopedDeclaration, ScopedVerb

Item = str | date

ANY = ast.Quantifier("ANY")
EACH = ast.Quantifier("EACH")
DEFAULT_POS = ast.Pos(0, 0)  # shared by every verb's default ON, so EACH expands them together
TRAINEE = "trainee"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class Choice:
    """A resolved selector.

    `alternatives` is set when the selector used OR/AND: the solver picks one alternative,
    and every item in it goes together. Otherwise `quantifier` says how many of `items`
    are chosen: ANY (one), ALL, or `n OF`.
    """

    items: tuple[Item, ...]
    alternatives: tuple[frozenset[Item], ...] | None
    quantifier: ast.Quantifier
    pos: ast.Pos

    @property
    def single(self) -> bool:
        """Whether exactly one item is chosen."""
        if self.alternatives is not None:
            return all(len(a) == 1 for a in self.alternatives)
        return self.quantifier.kind == "ANY"


@dataclass(frozen=True)
class Statement:
    """One verb with every clause resolved."""

    verb: str
    target: Choice | ast.AdHoc | ast.Free
    on: Choice
    during: Choice
    across: Choice
    role: Choice | None
    pos: ast.Pos
    minutes: int | None = None
    continuous: bool = False
    label: str | None = None
    metric: str | None = None
    per: tuple[str, ...] | None = None
    beyond: int | None = None


@dataclass(frozen=True)
class Resolved:
    """One expanded copy of a declaration. `key` names the EACH items it was made for."""

    key: str
    statements: tuple[Statement, ...]
    gaps: tuple[ast.Gap, ...]


def resolve(scoped: ScopedDeclaration, dataset: Dataset) -> tuple[Resolved, ...]:
    """Resolve names and expand EACH. Raises SkedgeError on unknown or misused names."""
    names = _Names(dataset)
    statements = tuple(_statement(v, names, dataset) for v in scoped.verbs)
    return tuple(_expand(statements, scoped.gaps))


class _Names:
    """Every valid name per namespace, each mapping to the items it stands for."""

    def __init__(self, dataset: Dataset) -> None:
        self.session = frozenset(dataset.session_dates)
        self.spaces: dict[str, dict[str, frozenset[Item]]] = {
            "staff": _ids_and_categories(dataset.staff, dataset.staff_categories),
            "activity": _ids_and_categories(dataset.activities, dataset.activity_categories),
            "block": _ids_and_categories(dataset.blocks, dataset.block_categories),
            "date": date_names(dataset),
            "role": {
                r: frozenset({r})
                for r in POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES + (TRAINEE,)
            },
            "metric": {m: frozenset({m}) for m in dataset.metrics},
        }

    def lookup(self, ref: ast.Ref, namespace: str) -> frozenset[Item]:
        if ref.namespace != namespace:
            raise _error(f"expected a {namespace} name, not {ref.namespace}.{ref.name}", ref.pos)
        try:
            return self.spaces[namespace][ref.name]
        except KeyError:
            raise _error(f"unknown {namespace} name '{ref.name}'", ref.pos) from None


def name_listing(dataset: Dataset) -> dict[str, list[tuple[str, str]]]:
    """Every valid name per namespace with a short note, in listing order.

    Taken from the same table the resolver validates against, so what is listed, completed
    and accepted can never drift apart.
    """
    described = {
        "staff": {i: s.name for i, s in dataset.staff.items()},
        "activity": {i: a.name for i, a in dataset.activities.items()},
        "block": {i: f"{b.start:%H:%M}-{b.end:%H:%M}" for i, b in dataset.blocks.items()},
        "metric": {m: f"scale {v.scale_min:g}-{v.scale_max:g}" for m, v in dataset.metrics.items()},
    }
    listing = {}
    for namespace, names in _Names(dataset).spaces.items():
        rows = [
            (name, described.get(namespace, {}).get(name) or _note(namespace, name, items))
            for name, items in names.items()
        ]
        listing[namespace] = sorted(rows)
    return listing


def _note(namespace: str, name: str, items: frozenset[Item]) -> str:
    if namespace == "date":
        return next(iter(items)).isoformat() if len(items) == 1 else f"{len(items)} dates"
    if namespace == "role":
        if name in LIFEGUARD_ROLES:
            return "extra lifeguard on a water clinic"
        return "trainee" if name in TRAINEE_ROLES + (TRAINEE,) else "clinic position"
    return f"category, {len(items)} members"


def date_names(dataset: Dataset) -> dict[str, frozenset[Item]]:
    """Every name in the `date` namespace, in listing order.

    A weekday holds every date of the session that falls on it, so `ON date.monday` means
    one Monday and `ON EACH date.monday` means every Monday. An ordinal or `last_` name
    holds the single date of that occurrence, and exists only if the session reaches it.
    """
    session = dataset.session_dates
    names: dict[str, frozenset[Item]] = {
        "target": frozenset({dataset.target}),
        "session": frozenset(session),
    }
    by_weekday: dict[str, list[date]] = {}
    for day in session:
        by_weekday.setdefault(WEEKDAYS[day.weekday()], []).append(day)
    for weekday in WEEKDAYS:
        days = by_weekday.get(weekday)
        if not days:
            continue
        names[weekday] = frozenset(days)
        for ordinal, day in zip(ORDINALS, days, strict=False):
            names[f"{ordinal}_{weekday}"] = frozenset({day})
        names[f"last_{weekday}"] = frozenset({days[-1]})
    return names


def _ids_and_categories(items, categories) -> dict[str, frozenset[Item]]:
    return {**{i: frozenset({i}) for i in items}, **categories}


def _statement(scoped: ScopedVerb, names: _Names, dataset: Dataset) -> Statement:
    verb = scoped.verb
    target = verb.target
    if isinstance(target, ast.Selector):
        target = _choice(target, "activity", names)
    on = scoped.get(ast.On)
    during = scoped.get(ast.During)
    across = scoped.get(ast.Across)
    role = scoped.get(ast.Role)
    for_ = scoped.get(ast.For)
    label = scoped.get(ast.Label)
    metric = scoped.get(ast.MetricClause)
    per = scoped.get(ast.Per)
    on_choice = (
        _choice(on.selector, "date", names)
        if on
        else Choice(tuple(dataset.session_dates), None, EACH, DEFAULT_POS)
    )
    across_choice = (
        _choice(across.selector, "staff", names)
        if across
        else Choice(tuple(sorted(dataset.staff)), None, ANY, verb.pos)
    )
    statement = Statement(
        verb=verb.kind,
        target=target,
        on=_within_session(on_choice, names.session),
        during=_choice(during.selector, "block", names),
        across=across_choice,
        role=_choice(role.selector, "role", names) if role else None,
        pos=verb.pos,
        minutes=for_.minutes if for_ else None,
        continuous=for_.continuous if for_ else False,
        label=label.name if label else None,
        metric=next(iter(names.lookup(metric.ref, "metric"))) if metric else None,
        per=per.fields if per else None,
        beyond=per.beyond if per else None,
    )
    _check_pool(statement, dataset)
    return statement


def _check_pool(statement: Statement, dataset: Dataset) -> None:
    """Without ROLE, a positioned activity is staffed from the ACROSS pool, so ANY only."""
    if statement.verb != "TASK" or statement.role or not isinstance(statement.target, Choice):
        return
    across = statement.across
    if across.quantifier.kind in ("ANY", "EACH") and across.alternatives is None:
        return
    raise _error("ACROSS must be a plain pool (no ALL, OF, AND) unless ROLE is given", across.pos)


def _choice(selector: ast.Selector, namespace: str, names: _Names) -> Choice:
    has_operators = isinstance(selector.expr, ast.Or | ast.And)
    quantifier = selector.quantifier
    if quantifier and has_operators:
        raise _error("a quantifier cannot apply to an expression with OR or AND", selector.pos)
    alternatives = _alternatives(selector.expr, namespace, names)
    items = tuple(sorted({item for alt in alternatives for item in alt}, key=str))
    if has_operators:
        return Choice(items, tuple(alternatives), ANY, selector.pos)
    quantifier = quantifier or ANY
    if quantifier.kind in ("ALL", "OF", "EACH") and not items:
        raise _error("this set is empty", selector.pos)
    if quantifier.kind == "OF" and not 1 <= quantifier.n <= len(items):
        raise _error(f"{quantifier.n} OF a set of {len(items)}", selector.pos)
    return Choice(items, None, quantifier, selector.pos)


def _alternatives(expr: ast.Expr, namespace: str, names: _Names) -> list[frozenset[Item]]:
    if isinstance(expr, ast.Or):
        return [alt for item in expr.items for alt in _alternatives(item, namespace, names)]
    if isinstance(expr, ast.And):
        parts = [_alternatives(item, namespace, names) for item in expr.items]
        return [frozenset().union(*combo) for combo in product(*parts)]
    return [_set(expr, namespace, names)]


def _set(expr: ast.SetExpr, namespace: str, names: _Names) -> frozenset[Item]:
    if isinstance(expr, ast.Ref):
        return names.lookup(expr, namespace)
    if isinstance(expr, ast.DateLiteral):
        if namespace != "date":
            raise _error(f"expected a {namespace} name, not a date", expr.pos)
        return frozenset({expr.value})
    if isinstance(expr, ast.DateOffset):
        return frozenset({_one_date(expr.base, names) + timedelta(days=expr.days)})
    if isinstance(expr, ast.DateRange):
        start, end = _one_date(expr.start, names), _one_date(expr.end, names)
        if end < start:
            raise _error("date range ends before it starts", expr.pos)
        return frozenset(start + timedelta(days=i) for i in range((end - start).days + 1))
    left, right = _set(expr.left, namespace, names), _set(expr.right, namespace, names)
    return {"+": left | right, "-": left - right, "&": left & right}[expr.op]


def _one_date(expr: ast.Ref | ast.DateLiteral, names: _Names) -> date:
    days = _set(expr, "date", names)
    if len(days) != 1:
        raise _error("a date offset or range needs a single date here", expr.pos)
    return next(iter(days))


def _within_session(on: Choice, session: frozenset[Item]) -> Choice:
    items = tuple(d for d in on.items if d in session)
    alternatives = None
    if on.alternatives is not None:
        alternatives = tuple(a & session for a in on.alternatives if a & session)
    return replace(on, items=items, alternatives=alternatives)


def _expand(statements: tuple[Statement, ...], gaps: tuple[ast.Gap, ...]) -> Iterator[Resolved]:
    each: dict[ast.Pos, tuple[Item, ...]] = {}
    for statement in statements:
        for choice in _choices(statement):
            if choice.quantifier.kind == "EACH":
                each.setdefault(choice.pos, choice.items)
    positions = sorted(each, key=lambda pos: (pos.line, pos.column))
    for combo in product(*(each[pos] for pos in positions)):
        picked = dict(zip(positions, combo, strict=True))
        copies = tuple(_substitute(s, picked) for s in statements)
        key = ",".join(str(item) for item in combo if not isinstance(item, date))
        yield Resolved(key, copies, gaps)


def _choices(statement: Statement) -> Iterator[Choice]:
    for choice in (
        statement.target,
        statement.on,
        statement.during,
        statement.across,
        statement.role,
    ):
        if isinstance(choice, Choice):
            yield choice


def _substitute(statement: Statement, picked: dict[ast.Pos, Item]) -> Statement:
    def fix(choice):
        if isinstance(choice, Choice) and choice.quantifier.kind == "EACH":
            return Choice((picked[choice.pos],), None, ANY, choice.pos)
        return choice

    return replace(
        statement,
        target=fix(statement.target),
        on=fix(statement.on),
        during=fix(statement.during),
        across=fix(statement.across),
        role=fix(statement.role),
    )


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)
