"""Turn a checked declaration into statements over concrete items from a Dataset.

Names are looked up, set expressions evaluated, and `EACH_OF` expanded into independent
copies of the declaration. A copy is what the solver compiles.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from puppet_strings.model import (
    LIFEGUARD_ROLES,
    ORDINALS,
    POSITION_ROLES,
    TRAINEE_ROLES,
    Dataset,
)
from puppet_strings.skedge import ast

Item = str | date

ALL = "all"  # every item, as one requirement; an item on its own is ALL of one
ANY = "any"  # n of the items, the solver's choice
POOL = "pool"  # any of the items match
TRAINEE = "trainee"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_POS = ast.Pos(0, 0)


@dataclass(frozen=True)
class Choice:
    """A resolved selector: its items and how they are taken.

    `var` names a choice a binding line makes once for the whole declaration; every
    selector carrying the same `var` shares it.
    """

    items: tuple[Item, ...]
    kind: str
    n: int = 1
    var: str | None = None
    pos: ast.Pos = DEFAULT_POS


@dataclass(frozen=True)
class Pattern:
    """`<who> DOING <what> …`, `<who> FREE …` or (`busy`) `<who> NOT FREE …`, resolved."""

    who: Choice
    what: Choice | ast.Task | None
    busy: bool
    during: Choice | None
    on: Choice
    role: Choice | None
    minutes: int | None
    with_: frozenset[str] | None
    without: frozenset[str] | None
    pos: ast.Pos


@dataclass(frozen=True)
class Requirement:
    """`REQUEST <who> DO <what> …` or `REQUEST <who> FREE …` (`what` is None), resolved."""

    who: Choice
    what: Choice | ast.Task | None
    during: Choice
    on: Choice
    role: Choice | None
    minutes: int | None
    with_: frozenset[str] | None
    without: frozenset[str] | None
    label: str | None
    pos: ast.Pos


@dataclass(frozen=True)
class Forbid:
    """`REQUEST <who> NOT DO …`: no assignment of `who` matches the pattern.

    For `REQUEST <who> NOT FREE …` the pattern is the busy one, and `who` must match it
    in every block it allows.
    """

    who: Choice
    pattern: Pattern
    pos: ast.Pos


@dataclass(frozen=True)
class Count:
    """`REQUEST|PREFER <amount> <pattern> [CONSECUTIVE]`, resolved."""

    prefer: bool
    amount: ast.Amount
    pattern: Pattern
    consecutive: bool
    pos: ast.Pos


@dataclass(frozen=True)
class Score:
    """`PREFER <pattern> MAXIMIZE|MINIMIZE metric.x(args)`, with the arguments as a key."""

    pattern: Pattern
    maximize: bool
    metric: str
    key: tuple[str, ...]
    pos: ast.Pos


@dataclass(frozen=True)
class Condition:
    """`IF` or (`unless`) `UNLESS`, resolved. Without an amount it asks for one match."""

    unless: bool
    amount: ast.Amount | None
    pattern: Pattern
    consecutive: bool


Statement = Requirement | Forbid | Count | Score


@dataclass(frozen=True)
class Resolved:
    """One expanded copy of a declaration. `key` names the EACH_OF items it was made for."""

    key: str
    bindings: dict[str, Choice]
    statements: tuple[Statement, ...]
    condition: Condition | None
    gaps: tuple[ast.Gap, ...]


@dataclass(frozen=True)
class Named:
    """What a name stands for: its items, and whether it is one item rather than a set."""

    items: frozenset[Item]
    single: bool


def resolve(declaration: ast.Declaration, dataset: Dataset) -> tuple[Resolved, ...]:
    """Resolve names and expand EACH_OF. Raises SkedgeError on unknown or misused names."""
    scope = _Scope(_Names(dataset), dataset)
    for binding in declaration.bindings:
        if binding.selector.quantifier == ast.ANY_OF:
            scope = scope.with_any(binding.selector)
    each = [
        (namespace, selector)
        for line in declaration.lines
        for namespace, selector in ast.selectors(line)
        if selector.quantifier == ast.EACH_OF
    ]
    return tuple(_expand(declaration, each, scope))


# -- names ------------------------------------------------------------------------------------


class _Names:
    """Every valid name per namespace."""

    def __init__(self, dataset: Dataset) -> None:
        roles = POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES + (TRAINEE,)
        self.spaces: dict[str, dict[str, Named]] = {
            "staff": _members(dataset.staff, dataset.staff_categories),
            "activity": _members(dataset.activities, dataset.activity_categories),
            "block": _members(dataset.blocks, dataset.block_categories),
            "date": date_names(dataset),
            "role": {r: Named(frozenset({r}), True) for r in roles},
            "metric": {m: Named(frozenset({m}), True) for m in dataset.metrics},
        }

    def lookup(self, ref: ast.Ref, namespace: str) -> Named:
        if ref.namespace != namespace:
            raise _error(f"expected a {namespace} name, not {ref.namespace}.{ref.name}", ref.pos)
        try:
            return self.spaces[namespace][ref.name]
        except KeyError:
            raise _error(f"unknown {namespace} name '{ref.name}'", ref.pos) from None


def _members(items, categories) -> dict[str, Named]:
    single = {i: Named(frozenset({i}), True) for i in items}
    sets = {c: Named(frozenset(members), False) for c, members in categories.items()}
    return {**single, **sets}


def date_names(dataset: Dataset) -> dict[str, Named]:
    """Every name in the `date` namespace: `target`, and `<scope>.<name>` per scope.

    The scopes are `session` (the target's), `season`, and each session by its own name.
    Within a scope, `all` and the weekdays are sets; `first`, `last` and the ordinal
    weekdays are items that exist only when the scope reaches them. `season` also holds
    each ordinal weekday as a set over the sessions: `season.first_mondays`.
    """
    names = {"target": Named(frozenset({dataset.target}), True)}
    scopes = {"session": dataset.session_dates, "season": dataset.season_dates, **dataset.sessions}
    for scope, dates in scopes.items():
        for name, named in _scope_names(dates).items():
            names[f"{scope}.{name}"] = named
    per_session = [_scope_names(dates) for dates in dataset.sessions.values()]
    occurrences = {n for s in per_session for n, v in s.items() if v.single and "_" in n}
    for name in occurrences:
        dates = frozenset().union(*(s[name].items for s in per_session if name in s))
        names[f"season.{name}s"] = Named(dates, False)
    return names


def _scope_names(dates: tuple[date, ...]) -> dict[str, Named]:
    names = {"all": Named(frozenset(dates), False)}
    if not dates:
        return names
    names["first"], names["last"] = _one(dates[0]), _one(dates[-1])
    by_weekday: dict[str, list[date]] = {}
    for day in dates:
        by_weekday.setdefault(WEEKDAYS[day.weekday()], []).append(day)
    for weekday, days in by_weekday.items():
        names[f"{weekday}s"] = Named(frozenset(days), False)
        for ordinal, day in zip(ORDINALS, days, strict=False):
            names[f"{ordinal}_{weekday}"] = _one(day)
        names[f"last_{weekday}"] = _one(days[-1])
    return names


def _one(day: date) -> Named:
    return Named(frozenset({day}), True)


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
            (name, described.get(namespace, {}).get(name) or _note(namespace, name, named))
            for name, named in names.items()
        ]
        listing[namespace] = sorted(rows)
    return listing


def _note(namespace: str, name: str, named: Named) -> str:
    if namespace == "date":
        return next(iter(named.items)).isoformat() if named.single else f"{len(named.items)} dates"
    if namespace == "role":
        if name in LIFEGUARD_ROLES:
            return "extra lifeguard on a water clinic"
        return "trainee" if name in TRAINEE_ROLES + (TRAINEE,) else "clinic position"
    return f"category, {len(named.items)} members"


# -- expansion --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scope:
    """What the variables stand for while one copy of a declaration is resolved.

    `each` holds the item of every EACH_OF selector, by position; `vars` the EACH_OF
    variables by name; `anys` the ANY_n_OF binding lines.
    """

    names: _Names
    dataset: Dataset
    each: dict[ast.Pos, Item] = field(default_factory=dict)
    vars: dict[str, tuple[Item, str]] = field(default_factory=dict)
    anys: dict[str, tuple[Choice, str]] = field(default_factory=dict)

    def with_each(self, selector: ast.Selector, item: Item, namespace: str) -> "_Scope":
        each = {**self.each, selector.pos: item}
        variables = dict(self.vars)
        if selector.var:
            variables[selector.var] = (item, namespace)
        return replace(self, each=each, vars=variables)

    def with_any(self, selector: ast.Selector) -> "_Scope":
        namespace = _namespace_of(selector.expr, self)
        items, single = _evaluate(selector.expr, namespace, self)
        if single:
            raise _error("is one item and takes no quantifier", selector.pos)
        choice = Choice(_sorted(items), ANY, selector.n, selector.var, selector.pos)
        return replace(self, anys={**self.anys, selector.var: (choice, namespace)})


def _expand(declaration: ast.Declaration, each: list, scope: _Scope) -> Iterator[Resolved]:
    if not each:
        yield _copy(declaration, scope)
        return
    (namespace, selector), rest = each[0], each[1:]
    namespace = namespace or _namespace_of(selector.expr, scope)
    items, single = _evaluate(selector.expr, namespace, scope)
    if single:
        raise _error("is one item and takes no quantifier", selector.pos)
    for item in _sorted(items):
        yield from _expand(declaration, rest, scope.with_each(selector, item, namespace))


def _copy(declaration: ast.Declaration, scope: _Scope) -> Resolved:
    conditions = declaration.conditions
    return Resolved(
        key=", ".join(str(item) for item in scope.each.values()),
        bindings={name: choice for name, (choice, _) in scope.anys.items()},
        statements=tuple(_statement(s, scope) for s in declaration.statements),
        condition=_condition(conditions[0], scope) if conditions else None,
        gaps=declaration.gaps,
    )


def _statement(statement: ast.Statement, scope: _Scope) -> Statement:
    if isinstance(statement, ast.Count):
        pattern = _pattern(statement.pattern, scope)
        return Count(
            statement.prefer, statement.amount, pattern, statement.consecutive, statement.pos
        )
    if isinstance(statement, ast.Score):
        return _score(statement, scope)
    who = _choice(statement.who, "staff", scope, pool=False)
    parts = _parts(statement.what, statement.clauses, scope, pool=statement.negated)
    if statement.negated:
        pool = Choice(who.items, POOL, pos=who.pos)
        pattern = Pattern(pool, busy=statement.what is None, **parts, pos=statement.pos)
        return Forbid(who, pattern, statement.pos)
    return Requirement(who, label=statement.label, **parts, pos=statement.pos)


def _pattern(pattern: ast.Pattern, scope: _Scope) -> Pattern:
    who = _choice(pattern.who, "staff", scope, pool=True)
    parts = _parts(pattern.what, pattern.clauses, scope, pool=True)
    return Pattern(who, busy=pattern.busy, **parts, pos=pattern.pos)


def _parts(what: ast.Target, clauses: tuple[ast.Clause, ...], scope: _Scope, pool: bool) -> dict:
    """The target and clauses shared by requirements and patterns, resolved."""
    during = ast.clause(clauses, ast.During)
    on = ast.clause(clauses, ast.On)
    role = ast.clause(clauses, ast.AsRole)
    for_ = ast.clause(clauses, ast.For)
    with_ = ast.clause(clauses, ast.With)
    without = ast.clause(clauses, ast.Without)
    target = Choice((scope.dataset.target,), POOL if pool else ALL)
    return {
        "what": _choice(what, "activity", scope, pool) if isinstance(what, ast.Selector) else what,
        "during": _choice(during.selector, "block", scope, pool) if during else None,
        "on": _choice(on.selector, "date", scope, pool) if on else target,
        "role": _choice(role.selector, "role", scope, pool) if role else None,
        "minutes": for_.minutes if for_ else None,
        "with_": _staff(with_.staff, scope) if with_ else None,
        "without": _staff(without.staff, scope) if without else None,
    }


def _staff(expr: ast.SetExpr, scope: _Scope) -> frozenset[str]:
    items, _ = _evaluate(expr, "staff", scope)
    return items


def _condition(condition: ast.Condition, scope: _Scope) -> Condition:
    pattern = _pattern(condition.pattern, scope)
    return Condition(condition.unless, condition.amount, pattern, condition.consecutive)


def _score(statement: ast.Score, scope: _Scope) -> Score:
    metric = next(iter(scope.names.lookup(statement.metric, "metric").items))
    keys = scope.dataset.metrics[metric].keys
    args = [_argument(a, scope) for a in statement.args]
    if tuple(namespace for _, namespace in args) != keys:
        raise _error("metric arguments do not match its keys", statement.pos)
    key = tuple(item.isoformat() if isinstance(item, date) else item for item, _ in args)
    pattern = _pattern(statement.pattern, scope)
    return Score(pattern, statement.maximize, metric, key, statement.pos)


def _argument(arg: ast.Var | ast.Ref, scope: _Scope) -> tuple[Item, str]:
    if isinstance(arg, ast.Var):
        if arg.name in scope.vars:
            return scope.vars[arg.name]
        if arg.name in scope.anys:
            raise _error("metric argument must be one item", arg.pos)
        raise _error(f"unknown variable '{arg.name}'", arg.pos)
    named = scope.names.lookup(arg, arg.namespace)
    if not named.single:
        raise _error("metric argument must be one item", arg.pos)
    return next(iter(named.items)), arg.namespace


# -- selectors and sets -----------------------------------------------------------------------


def _choice(selector: ast.Selector, namespace: str, scope: _Scope, pool: bool) -> Choice:
    if selector.quantifier == ast.EACH_OF:
        return Choice((scope.each[selector.pos],), POOL if pool else ALL, pos=selector.pos)
    expr = selector.expr
    if isinstance(expr, ast.Var) and expr.name in scope.anys:
        if selector.quantifier:
            raise _error(
                f"'{expr.name}' is chosen by its binding and takes no quantifier", expr.pos
            )
        choice, bound = scope.anys[expr.name]
        _expect(namespace, bound, expr)
        return replace(choice, kind=POOL if pool else ANY, pos=selector.pos)
    items, single = _evaluate(expr, namespace, scope)
    if namespace == "date":
        items = frozenset(d for d in items if d in scope.dataset.calendar)
    if pool:
        return Choice(_sorted(items), POOL, pos=selector.pos)
    if selector.quantifier is None:
        if not single:
            raise _error("needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF", selector.pos)
        return Choice(_sorted(items), ALL, pos=selector.pos)
    if single:
        raise _error("is one item and takes no quantifier", selector.pos)
    if selector.quantifier == ast.ALL_OF:
        return Choice(_sorted(items), ALL, pos=selector.pos)
    return Choice(_sorted(items), ANY, selector.n, pos=selector.pos)


def _evaluate(expr: ast.SetExpr, namespace: str, scope: _Scope) -> tuple[frozenset[Item], bool]:
    """The items an expression stands for, and whether it is one item."""
    if isinstance(expr, ast.Ref):
        named = scope.names.lookup(expr, namespace)
        return named.items, named.single
    if isinstance(expr, ast.Var):
        if expr.name in scope.vars:
            item, bound = scope.vars[expr.name]
            _expect(namespace, bound, expr)
            return frozenset({item}), True
        if expr.name in scope.anys:
            raise _error(f"'{expr.name}' is chosen by the solver and must stand alone", expr.pos)
        raise _error(f"unknown variable '{expr.name}'", expr.pos)
    if isinstance(expr, ast.DateLiteral):
        if namespace != "date":
            raise _error(f"expected a {namespace} name, not a date", expr.pos)
        return frozenset({expr.value}), True
    if isinstance(expr, ast.DateOffset):
        return frozenset({_one_date(expr.base, scope) + timedelta(days=expr.days)}), True
    if isinstance(expr, ast.DateRange):
        start, end = _one_date(expr.start, scope), _one_date(expr.end, scope)
        if end < start:
            raise _error("date range ends before it starts", expr.pos)
        days = frozenset(start + timedelta(days=i) for i in range((end - start).days + 1))
        return days, False
    left, _ = _evaluate(expr.left, namespace, scope)
    right, _ = _evaluate(expr.right, namespace, scope)
    return {"+": left | right, "-": left - right, "&": left & right}[expr.op], False


def _one_date(expr: ast.SetExpr, scope: _Scope) -> date:
    items, single = _evaluate(expr, "date", scope)
    if not single:
        raise _error("needs a single date here", expr.pos)
    return next(iter(items))


def _namespace_of(expr: ast.SetExpr, scope: _Scope) -> str:
    """The namespace a binding line's set belongs to, from the first name in it."""
    if isinstance(expr, ast.Ref):
        return expr.namespace
    if isinstance(expr, ast.Var):
        if expr.name in scope.vars:
            return scope.vars[expr.name][1]
        if expr.name in scope.anys:
            return scope.anys[expr.name][1]
        raise _error(f"unknown variable '{expr.name}'", expr.pos)
    if isinstance(expr, ast.SetOp):
        return _namespace_of(expr.left, scope)
    return "date"


def _expect(namespace: str, actual: str, var: ast.Var) -> None:
    if namespace != actual:
        raise _error(f"expected a {namespace} name, not '{var.name}'", var.pos)


def _sorted(items: frozenset[Item]) -> tuple[Item, ...]:
    return tuple(sorted(items, key=str))


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)
