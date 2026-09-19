"""Turn a checked declaration into statements over concrete items from a Dataset.

Names are looked up, set expressions evaluated, and `EACH_OF` expanded into independent
copies of the declaration. A copy is what the solver compiles.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from difflib import get_close_matches

from puppet_strings.model import (
    CARDINAL_WORDS,
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    TRAINEE_ROLES,
    Dataset,
)
from puppet_strings.names import normalize
from puppet_strings.skedge import ast
from puppet_strings.skedge.namespaces import (
    ACTIVITIES,
    BLOCKS,
    CABIN_ACTS,
    CLINICS,
    DATES,
    KEY_FIELDS,
    METRICS,
    ROLES,
    STAFF,
)
from puppet_strings.skedge.namespaces import ALL as ALL_NAME  # `all`, not the quantifier

SESSION = "session"  # where a numbered main season span hangs in the `dates` tree
OTHER = "other"  # where a span that is not a numbered session hangs
WEEK = "week"

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
    """`PREFER <pattern> MAXIMIZE|MINIMIZE metrics.x(args)`, with the arguments as a key."""

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


def is_prefer(statement) -> bool:
    """Whether a statement asks for something rather than requiring it.

    True of a `PREFER` in either form, written (`ast.Score`, `ast.Count`) or resolved, so
    that the validator and the compiler decide what a preference is the same way.
    """
    scores = (Score, ast.Score)
    counts = (Count, ast.Count)
    return isinstance(statement, scores) or (isinstance(statement, counts) and statement.prefer)


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
            STAFF: _members(dataset.staff, dataset.staff_categories),
            ACTIVITIES: activity_names(dataset),
            BLOCKS: _members(dataset.blocks, dataset.block_categories),
            DATES: date_names(dataset),
            ROLES: {r: Named(frozenset({r}), True) for r in roles},
            METRICS: {m: Named(frozenset({m}), True) for m in dataset.metrics},
        }

    def lookup(self, ref: ast.Ref, namespace: str) -> Named:
        if ref.namespace != namespace:
            raise _error(
                f"expected a name from {namespace}, not {ref.namespace}.{ref.name}", ref.pos
            )
        try:
            return self.spaces[namespace][ref.name]
        except KeyError:
            raise _error(
                f"unknown name '{namespace}.{ref.name}'{self._suggest(namespace, ref.name)}",
                ref.pos,
            ) from None

    def _suggest(self, namespace: str, name: str) -> str:
        """The nearest name there is, so a near miss says what to write instead."""
        close = get_close_matches(name, self.spaces[namespace], n=1, cutoff=0.6)
        return f"; did you mean '{namespace}.{close[0]}'?" if close else ""


def _members(items, categories) -> dict[str, Named]:
    single = {i: Named(frozenset({i}), True) for i in items}
    sets = {c: Named(frozenset(members), False) for c, members in categories.items()}
    return {**single, **sets}


def activity_names(dataset: Dataset) -> dict[str, Named]:
    """Every name in the `activities` namespace.

    Clinics and cabin acts are staffed the same way but are different things — one comes
    from Clinic_Data and runs for whoever signs up, the other from the cabin act board and
    belongs to one cabin on one day — so each has its own branch and neither can be picked
    up by accident. `activities.all` is deliberately both: it is the only name that means
    every activity there is.

    A clinic is named by itself or by its Clinic_Data category. A cabin act is named by its
    cabin and nothing else: `activities.cabin_acts.p4` is P4's act, and which day's act
    that is comes from the dates the request is about. Its own generated id is not a name,
    because nobody should have to write a date into one.
    """
    clinics = {i: a for i, a in dataset.activities.items() if not a.cabin}
    cabin_acts = {i: a for i, a in dataset.activities.items() if a.cabin}
    names = {ALL_NAME: Named(frozenset(dataset.activities), False)}
    _add(
        names,
        CLINICS,
        {
            ALL_NAME: Named(frozenset(clinics), False),
            **_members(clinics, dataset.activity_categories),
        },
    )
    _add(
        names,
        CABIN_ACTS,
        {
            ALL_NAME: Named(frozenset(cabin_acts), False),
            **{cabin: Named(ids, False) for cabin, ids in _cabin_categories(cabin_acts).items()},
        },
    )
    return names


def _cabin_categories(cabin_acts: Mapping[str, object]) -> dict[str, frozenset[str]]:
    """`activities.cabin_acts.p4` is P4's act on every day the cabin act sheets cover."""
    by_cabin: dict[str, set[str]] = {}
    for activity_id, activity in cabin_acts.items():
        by_cabin.setdefault(normalize(activity.cabin), set()).add(activity_id)
    return {cabin: frozenset(ids) for cabin, ids in by_cabin.items()}


def date_names(dataset: Dataset) -> dict[str, Named]:
    """Every name in the `dates` namespace.

    The tree is the Calendar sheet read out loud, and every span in it carries exactly the
    same names, so what can be said of one can be said of any other:

        dates.season.all                     every camp day
        dates.session.four.all               every date of session 4
        dates.session.four.mondays           every Monday of it
        dates.session.four.week.two.all      every date of its second week
        dates.session.four.week.two.monday   one date
        dates.other.family_camp.all          a span that is not a numbered session

    Every name here is the same on every day of the season, and every one of them says
    which span it means. `dates.target` is the only name that follows the date being
    scheduled; a request about "this session" names the session.
    """
    names = {"target": Named(frozenset({dataset.target}), True)}
    _add(names, "season", _span_names(dataset.season_dates))
    for span in dataset.spans:
        _add(names, _span_path(span), _one_span(dataset, span))
    return names


def _span_path(span) -> str:
    """Where a span hangs: a numbered session by its number, anything else by its name."""
    if span.session is not None:
        return f"{SESSION}.{CARDINAL_WORDS[span.session - 1]}"
    return f"{OTHER}.{span.id}"


def _one_span(dataset: Dataset, span) -> dict[str, Named]:
    """One span's own names, with its weeks nested underneath."""
    names = _span_names(dataset.span_dates(span))
    for week, dates in dataset.span_weeks(span).items():
        _add(names, f"{WEEK}.{CARDINAL_WORDS[week - 1]}", _week_names(dates))
    return names


def _span_names(dates: tuple[date, ...]) -> dict[str, Named]:
    """The names any run of dates carries: the whole run, its ends, and its weekdays.

    There is no `first_monday` or `last_friday`. One of them meant a date and its plural
    meant one date per session, a letter apart, and which of them existed depended on how
    long the season happened to be. A week's weekday says the same thing and says it once.
    """
    names = {ALL_NAME: Named(frozenset(dates), False)}
    if not dates:
        return names
    names["first"], names["last"] = _one(dates[0]), _one(dates[-1])
    for weekday, days in _by_weekday(dates).items():
        names[f"{weekday}s"] = Named(frozenset(days), False)
    return names


def _week_names(dates: tuple[date, ...]) -> dict[str, Named]:
    """A week's names.

    A week reaches each weekday at most once, so `monday` is the one Monday there is.
    """
    names = {ALL_NAME: Named(frozenset(dates), False)}
    if dates:
        names["first"], names["last"] = _one(dates[0]), _one(dates[-1])
    for weekday, days in _by_weekday(dates).items():
        names[weekday] = _one(days[0])
    return names


def _by_weekday(dates: tuple[date, ...]) -> dict[str, list[date]]:
    by_weekday: dict[str, list[date]] = {}
    for day in dates:
        by_weekday.setdefault(WEEKDAYS[day.weekday()], []).append(day)
    return by_weekday


def _add(names: dict[str, Named], scope: str, under: dict[str, Named]) -> None:
    """Graft a span's names under a scope; its own name is the scope with nothing after it."""
    for name, named in under.items():
        names[f"{scope}.{name}" if name else scope] = named


def _one(day: date) -> Named:
    return Named(frozenset({day}), True)


def name_listing(dataset: Dataset) -> dict[str, list[tuple[str, str]]]:
    """Every valid name per namespace with a short note, in listing order.

    Taken from the same table the resolver validates against, so what is listed, completed
    and accepted can never drift apart.
    """
    described = {
        STAFF: {i: s.name for i, s in dataset.staff.items()},
        ACTIVITIES: {
            **{f"{CLINICS}.{i}": a.name for i, a in dataset.activities.items() if not a.cabin},
            **{
                f"{CABIN_ACTS}.{normalize(a.cabin)}": f"cabin {a.cabin}"
                for a in dataset.activities.values()
                if a.cabin
            },
        },
        BLOCKS: {i: f"{b.start:%H:%M}-{b.end:%H:%M}" for i, b in dataset.blocks.items()},
        METRICS: {m: f"scale {v.scale_min:g}-{v.scale_max:g}" for m, v in dataset.metrics.items()},
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
    if namespace == DATES:
        if named.single:
            day = next(iter(named.items))
            return f"{day.isoformat()} ({day:%A})"
        return f"{len(named.items)} date" + ("" if len(named.items) == 1 else "s")
    if namespace == ROLES:
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
    who = (
        _anyone(statement, scope)
        if statement.who is None
        else _choice(statement.who, STAFF, scope, pool=False)
    )
    parts = _parts(statement.what, statement.clauses, scope, pool=statement.negated)
    if statement.negated:
        pool = Choice(who.items, POOL, pos=who.pos)
        pattern = Pattern(pool, busy=statement.what is None, **parts, pos=statement.pos)
        return Forbid(who, pattern, statement.pos)
    return Requirement(who, label=statement.label, **parts, pos=statement.pos)


def _anyone(statement: ast.Requirement, scope: _Scope) -> Choice:
    """The subject of `REQUEST <activity>`, which names none: anyone the activity allows.

    The request is sugar for `REQUEST ANY_1_OF staff.all DO <activity>`. Asking that one
    person holds a position of an activity asks that it runs at all, and a running activity
    fills every position it has (`solver.structural`), so naming one person here asks for
    all of the people it needs — which is why the activity's positions are the only place
    who may do it has to be written down.
    """
    if not isinstance(statement.what, ast.Selector):
        raise _error("name an activity here, not a task", statement.pos)
    everyone = frozenset(scope.dataset.staff_categories.get(ALL_NAME, frozenset()))
    return Choice(_sorted(everyone), ANY, 1, pos=statement.pos)


def _pattern(pattern: ast.Pattern, scope: _Scope) -> Pattern:
    who = _choice(pattern.who, STAFF, scope, pool=True)
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
    # The dates come first: an activity that belongs to one day, such as a cabin act, is
    # only the one the request is about, so `activities.cabin_acts.p4 ON <a date>` is one
    # thing and needs no quantifier, while the same name over a week is five.
    when = _choice(on.selector, DATES, scope, pool) if on else target
    return {
        "what": _choice(what, ACTIVITIES, scope, pool, when.items)
        if isinstance(what, ast.Selector)
        else what,
        "during": _choice(during.selector, BLOCKS, scope, pool) if during else None,
        "on": when,
        "role": _choice(role.selector, ROLES, scope, pool) if role else None,
        "minutes": for_.minutes if for_ else None,
        "with_": _staff(with_.staff, scope) if with_ else None,
        "without": _staff(without.staff, scope) if without else None,
    }


def _staff(expr: ast.SetExpr, scope: _Scope) -> frozenset[str]:
    items, _ = _evaluate(expr, STAFF, scope)
    return items


def _condition(condition: ast.Condition, scope: _Scope) -> Condition:
    pattern = _pattern(condition.pattern, scope)
    return Condition(condition.unless, condition.amount, pattern, condition.consecutive)


def _score(statement: ast.Score, scope: _Scope) -> Score:
    metric = next(iter(scope.names.lookup(statement.metric, METRICS).items))
    keys = scope.dataset.metrics[metric].keys
    args = [_argument(a, scope) for a in statement.args]
    if tuple(KEY_FIELDS.get(namespace, namespace) for _, namespace in args) != keys:
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


def _choice(
    selector: ast.Selector,
    namespace: str,
    scope: _Scope,
    pool: bool,
    when: tuple[Item, ...] = (),
) -> Choice:
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
    if namespace == DATES:
        items = frozenset(d for d in items if d in scope.dataset.calendar)
    if namespace == ACTIVITIES:
        items, single = _on_those_days(items, single, when, scope)
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


def _on_those_days(
    items: frozenset[Item], single: bool, when: tuple[Item, ...], scope: _Scope
) -> tuple[frozenset[Item], bool]:
    """Keep only the activities that exist on the dates the request is about.

    A clinic belongs to no day and always survives. A cabin act belongs to one, so a name
    that stands for a cabin's act all season, `activities.cabin_acts.p4`, comes down to the
    one act on the day being asked about — and is then a single thing, which is why the
    request needs no quantifier for it. A name holding both kinds stays a set.
    """
    dated = {i: scope.dataset.activities[i].day for i in items}
    if not any(day is not None for day in dated.values()):
        return items, single
    kept = frozenset(i for i, day in dated.items() if day is None or day in when)
    if all(day is not None for day in dated.values()):
        return kept, len(kept) == 1
    return kept, False


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
        if namespace != DATES:
            raise _error(f"expected a name from {namespace}, not a date", expr.pos)
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
    items, single = _evaluate(expr, DATES, scope)
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
    return DATES


def _expect(namespace: str, actual: str, var: ast.Var) -> None:
    if namespace != actual:
        raise _error(f"expected a name from {namespace}, not '{var.name}'", var.pos)


def _sorted(items: frozenset[Item]) -> tuple[Item, ...]:
    return tuple(sorted(items, key=str))


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)
