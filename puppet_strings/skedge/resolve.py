"""Turn a checked declaration into statements over concrete items from a Dataset.

Names are looked up, set expressions evaluated, and `EACH` expanded into independent
copies of the declaration. A copy is what the solver compiles.
"""

from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from difflib import get_close_matches
from functools import cache

from puppet_strings.model import (
    LIFEGUARD_ROLES,
    POSITION_ROLES,
    SESSION_TARGET,
    TARGET,
    TRAINEE_ROLES,
    WEEK_PREFIX,
    Dataset,
    MappingTable,
)
from puppet_strings.names import normalize
from puppet_strings.skedge import ast
from puppet_strings.skedge.namespaces import (
    ACTIVITIES,
    AT_CABIN_ACT,
    AT_REST_HOUR,
    BLOCKS,
    CABIN_ACTS,
    CLINICS,
    DATES,
    KEY_NAMESPACES,
    MAPPINGS,
    ROLES,
    STAFF,
)
from puppet_strings.skedge.namespaces import ALL as ALL_NAME  # `all`, not the quantifier
from puppet_strings.skedge.parser import parse_default, parse_domain

Item = str | date

ALL = "all"  # every item, as one requirement; an item on its own is ALL of one
ANY = "any"  # n of the items, the solver's choice
POOL = "pool"  # any of the items match
COUNT = "count"  # how many of the items the rest holds for, compared with `n` by `bound`
TRAINEE = "trainee"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_POS = ast.Pos(0, 0)


@dataclass(frozen=True)
class Choice:
    """A resolved selector: its items and how they are taken.

    `var` names a choice a binding line makes once for the whole declaration; every
    selector carrying the same `var` shares it.

    `parts` are choices taken *as well as* these items, which is what a bound name added
    into a set means: `ALL {staff.charlton + videographer}` is charlton, always, and
    whoever the solver picked for `videographer`, whoever that turns out to be.

    `units` are the groups an ANY choice takes as one thing each, alongside its items:
    `AT_LEAST 1 {staff.x + (ALL {staff.y + staff.z})}` is x, or else y and z both. A group
    chosen brings what it chooses in turn.

    `consecutive` is `CONSECUTIVE` on blocks: the n chosen, or the ones counted, are next
    to each other, and a pool of blocks is measured a run at a time.

    `bound` is a COUNT's AT_LEAST, AT_MOST or EXACTLY.
    """

    items: tuple[Item, ...]
    kind: str
    n: int = 1
    var: str | None = None
    parts: tuple["Choice", ...] = ()
    pos: ast.Pos = DEFAULT_POS
    consecutive: bool = False
    units: tuple["Choice", ...] = ()
    bound: str | None = None


@dataclass(frozen=True)
class Company:
    """Who a WITH or WITHOUT counts: `n` of these staff by `bound`, or (`n` None) all of them.

    `roles` are the roles they count in, from an AS_ROLE written after them; None is any.
    """

    staff: frozenset[str]
    n: int | None
    bound: str = ast.AT_LEAST
    roles: frozenset[str] | None = None


@dataclass(frozen=True)
class Pattern:
    """`<who> DO <what> …`, `<who> FREE …` or (`busy`) `<who> BUSY …`, resolved.

    `minutes` is a FOR that picks out assignments of that length, compared by
    `length_bound`; a FOR that measures a pool is a Tally's `measure` instead.
    """

    who: Choice
    what: Choice | ast.Task | None
    busy: bool
    during: Choice | None
    on: Choice
    role: Choice | None
    minutes: int | None
    with_: Company | None
    without: Company | None
    pos: ast.Pos
    length_bound: str = ast.EXACTLY


@dataclass(frozen=True)
class Requirement:
    """`REQUEST <who> DO <what> …`, `… FREE …` or (`busy`) `… BUSY …` (`what` None), resolved.

    Every set in it is taken whole (ALL), chosen from (ANY n, a count of AT_LEAST n), or
    pooled (POOL), where one of its items is chosen for each combination of the rest.
    `minutes` is the length of each quoted-task piece, compared by `length_bound`.
    """

    who: Choice
    what: Choice | ast.Task | None
    during: Choice
    on: Choice
    role: Choice | None
    minutes: int | None
    with_: Company | None
    without: Company | None
    label: str | None
    pos: ast.Pos
    busy: bool = False
    length_bound: str = ast.EXACTLY


@dataclass(frozen=True)
class Forbid:
    """`REQUEST <who> NOT DO …`: no assignment of `who` matches the pattern.

    A part of the pattern that is ALL rather than POOL was written ALL: then what is
    forbidden is an assignment for every one of its items together, and any one of them on
    its own is allowed.
    """

    who: Choice
    pattern: Pattern
    pos: ast.Pos


@dataclass(frozen=True)
class Level:
    """One count in a statement: how many of `choice`'s items the rest of it holds for.

    `field` is the Match field it counts: staff, activity, date or block.
    """

    field: str
    choice: Choice


@dataclass(frozen=True)
class Tally:
    """A statement with counts, or with a FOR measured over a pool, resolved.

    `levels` are its counts, outermost first: who, then what, then the dates, then the
    blocks. `pattern` is what is left once each is taken one item at a time, where a set
    taken ALL is one unit and a POOL is matched by any of its items; a counted field holds
    the whole set it counts. `measure` is a FOR over what the pattern pools, and `runs`
    says the pooled blocks are measured one run of adjacent blocks at a time.

    A REQUEST, a PREFER (`prefer`), and the test of a condition all take this form.
    """

    prefer: bool
    levels: tuple[Level, ...]
    pattern: Pattern
    measure: ast.Amount | None
    runs: bool
    pos: ast.Pos


@dataclass(frozen=True)
class Score:
    """`PREFER <pattern> MAXIMIZE|MINIMIZE mappings.x(args)`, with the arguments as a key."""

    pattern: Pattern
    maximize: bool
    mapping: str
    key: tuple[str, ...]
    pos: ast.Pos


@dataclass(frozen=True)
class Exclusion:
    """`EXCLUDE <who> DO '<label>' …`, resolved: who is out, when, and what to call it."""

    who: Choice
    label: str
    during: Choice | None  # None is every block the date has
    on: Choice
    pos: ast.Pos


@dataclass(frozen=True)
class Predicate:
    """One test of a condition, resolved. With no count and no FOR it asks for one match."""

    tally: Tally


@dataclass(frozen=True)
class Junction:
    """Tests joined by `AND` (`all`) or by `OR`, resolved."""

    all: bool
    parts: tuple["Predicate | Junction", ...]


@dataclass(frozen=True)
class Condition:
    """`IF` or (`unless`) `UNLESS`, resolved."""

    unless: bool
    test: Predicate | Junction


Statement = Requirement | Forbid | Tally | Score | Exclusion


def is_prefer(statement) -> bool:
    """Whether a statement asks for something rather than requiring it.

    True of a `PREFER` in either form, written (`ast.Score`, `ast.Preference`) or resolved,
    so that the validator and the compiler decide what a preference is the same way.
    """
    if isinstance(statement, Score | ast.Score | ast.Preference):
        return True
    return isinstance(statement, Tally) and statement.prefer


def asks(statement) -> bool:
    """Whether a statement asks for what it names, so that a quoted task in it may happen.

    A positive REQUEST does, unless all it says is how much there may be at most.
    """
    if isinstance(statement, Requirement):
        return True
    if not isinstance(statement, Tally) or statement.prefer:
        return False
    if any(level.choice.bound == ast.AT_MOST for level in statement.levels):
        return False
    return statement.measure is None or statement.measure.bound != ast.AT_MOST


@dataclass(frozen=True)
class Resolved:
    """One expanded copy of a declaration. `key` names the EACH items it was made for."""

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
    """Resolve names and expand EACH. Raises SkedgeError on unknown or misused names."""
    scope = _Scope(_names(dataset), dataset)
    for binding in declaration.bindings:
        if binding.selector.quantifier == ast.COUNT:
            scope = scope.with_any(binding.selector)
    each = [
        (namespace, selector)
        for line in declaration.lines
        for namespace, selector in ast.selectors(line)
        if selector.quantifier == ast.EACH
    ]
    return tuple(_expand(declaration, each, scope))


# -- names ------------------------------------------------------------------------------------


class _Names:
    """Every valid name per namespace."""

    def __init__(self, dataset: Dataset) -> None:
        roles = POSITION_ROLES + LIFEGUARD_ROLES + TRAINEE_ROLES + (TRAINEE,)
        self.dataset = dataset
        self.spaces: dict[str, dict[str, Named]] = {
            STAFF: _members(dataset.staff, dataset.staff_categories),
            ACTIVITIES: activity_names(dataset),
            BLOCKS: _members(dataset.blocks, dataset.block_categories),
            DATES: date_names(dataset),
            ROLES: {r: Named(frozenset({r}), True) for r in roles},
            MAPPINGS: {m: Named(frozenset({m}), True) for m in dataset.mappings},
        }
        self.domains: dict[str, tuple[str, frozenset[Item]]] = {}  # by `keys`/`value` text

    def lookup(self, ref: ast.Ref, namespace: str) -> Named:
        if ref.namespace != namespace:
            raise _error(
                f"expected a name from {namespace}, not {ref.namespace}.{ref.name}", ref.pos
            )
        try:
            return self.spaces[namespace][ref.name]
        except KeyError:
            if namespace == DATES and ref.name.split(".")[0] == SESSION_TARGET:
                raise ast.NoSession(
                    f"'{namespace}.{ref.name}' names no dates: {self.dataset.target} is in "
                    f"{self.dataset.this_span.name}, which is not a session. "
                    "The request is skipped when this date is solved",
                    ref.pos.line,
                    ref.pos.column,
                ) from None
            raise _error(
                f"unknown name '{namespace}.{ref.name}'{self._suggest(namespace, ref.name)}",
                ref.pos,
            ) from None

    def _suggest(self, namespace: str, name: str) -> str:
        """The nearest name there is, so a near miss says what to write instead."""
        close = get_close_matches(name, self.spaces[namespace], n=1, cutoff=0.6)
        return f"; did you mean '{namespace}.{close[0]}'?" if close else ""


def name_spaces(dataset: Dataset) -> dict[str, dict[str, Named]]:
    """Every valid name per namespace, with what it stands for."""
    return _names(dataset).spaces


def _names(dataset: Dataset) -> _Names:
    """The dataset's names, built once for it: every request resolved against it shares them."""
    return dataset.memo(_Names, lambda: _Names(dataset))


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
    because nobody should have to write a date into one. `at_cabin_act` and `at_rest_hour`
    split the board by the block each act is in, so each half is asked for on its own.
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
            AT_CABIN_ACT: Named(
                frozenset(i for i, a in cabin_acts.items() if not a.rest_hour), False
            ),
            AT_REST_HOUR: Named(frozenset(i for i, a in cabin_acts.items() if a.rest_hour), False),
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
        dates.session_4.all               every date of session 4
        dates.session_4.mondays           every Monday of it
        dates.session_4.week_2.all      every date of its second week
        dates.session_4.week_2.monday   one date
        dates.family_camp.all                a span that is not a numbered session

    Those names are the same on every day of the season. The ones with `target` in them
    follow the date being scheduled: `dates.target` itself, the session it falls in,
    `dates.session_target`, and the week of that session it falls in, `week_target`. A date
    outside the main season has no session, so there the session names do not exist.
    """
    names = {TARGET: Named(frozenset({dataset.target}), True)}
    _add(names, "season", _span_names(dataset.season_dates))
    for span in dataset.spans:
        _add(names, span.date_name, _one_span(dataset, span))
    if dataset.session is not None:
        _add(names, SESSION_TARGET, _target_session(dataset))
    return names


def _target_session(dataset: Dataset) -> dict[str, Named]:
    """The session the target falls in, as its number names it, and its week holding the target."""
    session = dataset.this_span
    names = _one_span(dataset, session)
    _add(names, f"{WEEK_PREFIX}{TARGET}", _week_names(dataset.week_dates))
    return names


def _one_span(dataset: Dataset, span) -> dict[str, Named]:
    """One span's own names, with its weeks nested underneath."""
    names = _span_names(dataset.span_dates(span))
    for week, dates in dataset.span_weeks(span).items():
        _add(names, f"{WEEK_PREFIX}{week}", _week_names(dates))
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
        MAPPINGS: {m: _mapping_note(v) for m, v in dataset.mappings.items()},
    }
    listing = {}
    for namespace, names in _names(dataset).spaces.items():
        rows = [
            (name, described.get(namespace, {}).get(name) or _note(namespace, name, named))
            for name, named in names.items()
        ]
        listing[namespace] = sorted(rows)
    return listing


def _mapping_note(mapping: MappingTable) -> str:
    keys = ", ".join(mapping.keys)
    if mapping.numeric:
        return f"{keys} -> {mapping.scale_min:g} to {mapping.scale_max:g}"
    return f"{keys} -> {mapping.value}"


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

    `each` holds the item of every EACH selector, by position, or the group it is on
    when the set holds one; `vars` the EACH variables by name; `anys` the EXACTLY n
    binding lines.
    """

    names: _Names
    dataset: Dataset
    each: dict[ast.Pos, "Item | _Unit"] = field(default_factory=dict)
    vars: dict[str, tuple[Item, str]] = field(default_factory=dict)
    anys: dict[str, tuple[Choice, str]] = field(default_factory=dict)

    def with_each(self, selector: ast.Selector, item: "Item | _Unit", namespace: str) -> "_Scope":
        each = {**self.each, selector.pos: item}
        variables = dict(self.vars)
        if selector.var:
            if isinstance(item, _Unit):
                raise _error(
                    f"'{selector.var}' names one item at a time, and {item} is a group",
                    item.group.pos,
                )
            variables[selector.var] = (item, namespace)
        return replace(self, each=each, vars=variables)

    def with_any(self, selector: ast.Selector) -> "_Scope":
        namespace = _namespace_of(selector.expr, self)
        items, single = _evaluate(selector.expr, namespace, self)
        _no_quantifier_on_one(selector.expr, single, selector.pos)
        choice = Choice(_sorted(items), ANY, selector.n, selector.var, pos=selector.pos)
        return replace(self, anys={**self.anys, selector.var: (choice, namespace)})


@dataclass(frozen=True)
class _Unit:
    """A group an EACH is on, as one copy: `EACH {staff.x + (ALL s)}` is two."""

    group: ast.Group

    def __str__(self) -> str:
        return ast.spoken(self.group)


def _expand(declaration: ast.Declaration, each: list, scope: _Scope) -> Iterator[Resolved]:
    if not each:
        # a cabin act split out of a season's worth that is not on these days is no copy
        with suppress(_AnotherDay):
            yield _copy(declaration, scope)
        return
    (namespace, selector), rest = each[0], each[1:]
    namespace = namespace or _namespace_of(selector.expr, scope)
    joined, parts = _split(selector.expr, scope)
    for var in (x for x in parts if isinstance(x, ast.Var)):
        raise _error(f"'{var.name}' is chosen by the solver, so EACH cannot split it", var.pos)
    units: list[Item | _Unit] = [_Unit(g) for g in parts]
    if joined is not None:
        items, single = _evaluate(joined, namespace, scope)
        if not parts:
            _no_quantifier_on_one(selector.expr, single, selector.pos)
        units = [*_sorted(items), *units]
    for unit in units:
        yield from _expand(declaration, rest, scope.with_each(selector, unit, namespace))


class _AnotherDay(Exception):
    """An EACH item is an activity that is not on the days its statement is about.

    `EACH activities.cabin_acts.all` splits over every act of the season, because which
    days a statement is about is only known once its ON is resolved. A copy whose act
    belongs to another day asks for nothing that can happen on its own days, so it is no
    copy at all -- rather than a request to run Friday's act on Wednesday.
    """


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
    if isinstance(statement, ast.Exclude):
        return _exclusion(statement, scope)
    if isinstance(statement, ast.Score):
        return _score(statement, scope)
    if isinstance(statement, ast.Preference):
        p = statement.pattern
        return _phrase(p.who, p.what, p.busy, p.clauses, scope, statement.pos, prefer=True)
    if statement.negated:
        who = _choice(statement.who, STAFF, scope, pool=False)
        if who.kind in (COUNT, POOL):
            who = _chosen(who)
        parts = _parts(statement.what, statement.clauses, scope, pool=True)
        pool = Choice(_everyone(who), POOL, pos=who.pos)
        pattern = Pattern(pool, busy=False, **parts, pos=statement.pos)
        return Forbid(who, pattern, statement.pos)
    return _phrase(
        statement.who,
        statement.what,
        statement.busy,
        statement.clauses,
        scope,
        statement.pos,
        label=statement.label,
    )


FIELDS = (("staff", "who"), ("activity", "what"), ("date", "on"), ("block", "during"))


def _phrase(
    who_selector: ast.Selector | None,
    what: ast.Target,
    busy: bool,
    clauses: tuple[ast.Clause, ...],
    scope: _Scope,
    pos: ast.Pos,
    prefer: bool = False,
    label: str | None = None,
    test: bool = False,
) -> Requirement | Tally:
    """A statement that says what happens: a requirement where it can be one, else a tally.

    A requirement takes each set whole, pools it, or chooses from it, which is all a
    statement with no count but one AT_LEAST, and no FOR measured over a pool, asks for.
    Anything else is counted: a PREFER is weighed by how close it comes, and a condition's
    test is true or false of the day, so both are always tallies.
    """
    who = (
        _anyone(what, scope, pos)
        if who_selector is None
        else _choice(who_selector, STAFF, scope, pool=False)
    )
    parts = _parts(what, clauses, scope, pool=False)
    for_ = ast.clause(clauses, ast.For)
    during, on = parts["during"], parts["on"]
    pooled = during is None or during.kind == POOL or on.kind == POOL
    measure = None
    if for_ is not None and (not isinstance(what, ast.Task) or pooled):
        if not pooled:
            raise _error(
                "FOR on an activity, FREE or BUSY measures its time across blocks, so the "
                "blocks take ANY: DURING ANY <blocks>",
                for_.pos,
            )
        measure = ast.Amount(for_.bound or ast.EXACTLY, for_.minutes, True, for_.pos)
        parts = {**parts, "minutes": None}
    chosen = {"who": who, **parts}
    levels = tuple(
        Level(field, chosen[key])
        for field, key in FIELDS
        if isinstance(chosen[key], Choice) and chosen[key].kind == COUNT
    )
    over_days = on.kind == POOL and len(on.items) > 1
    for level in levels:
        _countable(level, over_days)
    per_occurrence = over_days and any(level.field == "block" for level in levels)
    simple = _chosen_once(levels) and not per_occurrence
    if not (prefer or test) and measure is None and simple:
        for _, key in FIELDS:
            if isinstance(chosen[key], Choice) and chosen[key].kind == COUNT:
                chosen[key] = replace(chosen[key], kind=ANY, bound=None)
        if chosen["during"] is None:
            chosen["during"] = Choice(_whole_day(chosen["on"], scope), POOL, pos=pos)
        return Requirement(label=label, busy=busy, pos=pos, **chosen)
    if label is not None:
        raise _error(
            "a GAP is measured from what a REQUEST makes, so a labeled one takes no count "
            "but one AT_LEAST, and no FOR measured over ANY",
            pos,
        )
    runs = during is not None and during.consecutive and during.kind == POOL
    pattern = Pattern(busy=busy, pos=pos, **chosen)
    return Tally(prefer, levels, pattern, measure, runs, pos)


def _chosen_once(levels: tuple[Level, ...]) -> bool:
    """Whether a statement's counts can be one choice each, as a requirement makes them.

    AT_LEAST n picks n items and asks the rest of each. A requirement picks each set once,
    for everything else in it together, which is the same thing as long as every count but
    the innermost picks one: then there is one outer item for the inner pick to be about.
    """
    if any(level.choice.bound != ast.AT_LEAST for level in levels):
        return False
    return all(level.choice.n == 1 and not level.choice.units for level in levels[:-1])


def _countable(level: Level, over_days: bool) -> None:
    """A count's groups are each one thing counted, taken whole."""
    for unit in level.choice.units:
        if unit.kind != ALL or unit.parts:
            raise _error("a group in a count is taken whole, so it takes ALL", unit.pos)
        if level.field == "block" and over_days:
            raise _error(
                "a count of blocks over pooled dates counts each block on each date, so it "
                "takes no group",
                unit.pos,
            )
    if level.choice.consecutive and level.field != "block":
        raise _error("CONSECUTIVE is about blocks", level.choice.pos)


def _chosen(choice: Choice) -> Choice:
    """Left of NOT, a count or a pool of people chooses who the NOT is about."""
    if choice.kind == POOL:
        raise _error(_CHOSEN, choice.pos)
    if choice.bound != ast.AT_LEAST:
        raise _error(
            "left of NOT the subject is chosen, so a count there takes AT_LEAST: "
            f"AT_LEAST {choice.n} …",
            choice.pos,
        )
    return replace(choice, kind=ANY, bound=None)


def _whole_day(on: Choice, scope: _Scope) -> tuple[Item, ...]:
    """Every block of the dates a statement is about, for one that names no DURING."""
    blocks = {b.id for d in _everyone(on) for b in scope.dataset.blocks_on(d)}
    return _sorted(frozenset(blocks))


def _everyone(choice: Choice) -> tuple[Item, ...]:
    """Every item a choice could come to, whatever is chosen."""
    items = set(choice.items)
    for more in (*choice.parts, *choice.units):
        items.update(_everyone(more))
    return _sorted(frozenset(items))


def _exclusion(statement: ast.Exclude, scope: _Scope) -> Exclusion:
    """`EXCLUDE …`, resolved. Nothing in it is a choice: it says what the day is like."""
    who = _choice(statement.who, STAFF, scope, pool=False)
    during = ast.clause(statement.clauses, ast.During)
    on = ast.clause(statement.clauses, ast.On)
    return Exclusion(
        who=who,
        label=statement.label,
        during=_choice(during.selector, BLOCKS, scope, pool=False) if during else None,
        on=_choice(on.selector, DATES, scope, pool=False)
        if on
        else Choice((scope.dataset.target,), ALL),
        pos=statement.pos,
    )


def _anyone(what: ast.Target, scope: _Scope, pos: ast.Pos) -> Choice:
    """The subject of `REQUEST <activity>`, which names none: anyone the activity allows.

    The request is sugar for `REQUEST ANY staff.all DO <activity>`. Asking that someone
    holds a position of an activity asks that it runs at all, and a running activity fills
    every position it has (`solver.structural`), so naming one person here asks for all of
    the people it needs — which is why the activity's positions are the only place who may
    do it has to be written down.
    """
    if not isinstance(what, ast.Selector):
        raise _error("name an activity here, not a task", pos)
    everyone = frozenset(scope.dataset.staff_categories.get(ALL_NAME, frozenset()))
    return Choice(_sorted(everyone), POOL, pos=pos)


def _pattern(pattern: ast.Pattern, scope: _Scope) -> Pattern:
    """A pattern that is matched rather than counted: a score's."""
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
    blocks = _choice(during.selector, BLOCKS, scope, pool) if during else None
    if during and during.consecutive:
        if blocks.units:
            raise _error("CONSECUTIVE counts blocks one at a time, so no groups", during.pos)
        blocks = replace(blocks, consecutive=True)
    roles = _choice(role.selector, ROLES, scope, pool) if role else None
    several = roles is not None and (roles.kind == COUNT or len(roles.items) > 1)
    if several and not pool and roles.kind != POOL:
        raise _error("one role at a time: AS_ROLE takes a role, ANY or EACH", role.pos)
    return {
        "what": _choice(what, ACTIVITIES, scope, pool, _everyone(when))
        if isinstance(what, ast.Selector)
        else what,
        "during": blocks,
        "on": when,
        "role": roles,
        "minutes": for_.minutes if for_ else None,
        "length_bound": (for_.bound or ast.EXACTLY) if for_ else ast.EXACTLY,
        "with_": _company(with_, scope) if with_ else None,
        "without": _company(without, scope) if without else None,
    }


def _company(clause: ast.With | ast.Without, scope: _Scope) -> Company:
    """Who is alongside, and in which roles."""
    company = _companions(clause.selector, scope)
    if clause.role is None:
        return company
    role = clause.role
    if role.quantifier in (ast.ALL, ast.COUNT):
        raise _error("one role at a time: AS_ROLE takes a role, ANY or EACH", role.pos)
    roles = _choice(role, ROLES, scope, pool=True)
    return replace(company, roles=frozenset(roles.items))


def _companions(selector: ast.Selector, scope: _Scope) -> Company:
    """One name alongside, or several with a quantifier to say how many of them."""
    items, single = _evaluate(selector.expr, STAFF, scope)
    if selector.quantifier is None:
        if not single:
            raise _error("needs a quantifier: ALL or a count", selector.pos)
        return Company(items, None)
    _no_quantifier_on_one(selector.expr, single, selector.pos)
    if selector.quantifier == ast.COUNT:
        return Company(items, selector.n, selector.bound)
    return Company(items, None)


def _condition(condition: ast.Condition, scope: _Scope) -> Condition:
    return Condition(condition.unless, _test(condition.test, scope))


def _test(test: ast.Test, scope: _Scope) -> Predicate | Junction:
    if isinstance(test, ast.Junction):
        return Junction(test.all, tuple(_test(part, scope) for part in test.parts))
    p = test.pattern
    return Predicate(_phrase(p.who, p.what, p.busy, p.clauses, scope, test.pos, test=True))


def _score(statement: ast.Score, scope: _Scope) -> Score:
    mapping = _mapping(statement.mapping, scope)
    if not mapping.numeric:
        raise _error(
            f"mappings.{mapping.name} gives a name from {mapping.value}, not a number, so "
            "there is nothing to maximize or minimize",
            statement.mapping.pos,
        )
    key = _key(statement.args, mapping, scope, statement.pos)
    pattern = _pattern(statement.pattern, scope)
    return Score(pattern, statement.maximize, mapping.name, key, statement.pos)


# -- mappings ---------------------------------------------------------------------------------


def _mapping(ref: ast.Ref, scope: _Scope) -> MappingTable:
    name = next(iter(scope.names.lookup(ref, MAPPINGS).items))
    return scope.dataset.mappings[name]


def _key(
    args: tuple[ast.Var | ast.Ref, ...], mapping: MappingTable, scope: _Scope, pos: ast.Pos
) -> tuple[str, ...]:
    """The arguments of a call as the key of a row, each checked against its key's set."""
    if len(args) != len(mapping.keys):
        raise _error(
            f"wrong number of arguments: mappings.{mapping.name} takes "
            f"({', '.join(mapping.keys)}), not {len(args)}",
            pos,
        )
    key = []
    for arg, text in zip(args, mapping.keys, strict=True):
        item, namespace = _argument(arg, scope)
        expected, items = _domain(text, scope.names, scope.dataset)
        if namespace != expected:
            raise _error(
                f"mappings.{mapping.name} takes a name from {expected} here, not {namespace}",
                arg.pos,
            )
        if item not in items and judged(item, namespace, scope.dataset):
            raise _error(
                f"mappings.{mapping.name} takes {text} here, and '{item}' is not in it", arg.pos
            )
        key.append(item.isoformat() if isinstance(item, date) else item)
    return tuple(key)


def _argument(arg: ast.Var | ast.Ref, scope: _Scope) -> tuple[Item, str]:
    if not isinstance(arg, ast.Var | ast.Ref):  # a name defined as a set of several
        raise _error("mapping argument must be one item", arg.pos)
    if isinstance(arg, ast.Var):
        if arg.name in scope.vars:
            return scope.vars[arg.name]
        if arg.name in scope.anys:
            raise _error("mapping argument must be one item", arg.pos)
        raise _error(f"unknown variable '{arg.name}'", arg.pos)
    named = scope.names.lookup(arg, arg.namespace)
    if not named.single:
        raise _error("mapping argument must be one item", arg.pos)
    return next(iter(named.items)), arg.namespace


def _gives(call: ast.Call, scope: _Scope) -> tuple[MappingTable, str, frozenset[Item]]:
    """The mapping a call is to, and the namespace and set its value comes from."""
    mapping = _mapping(call.mapping, scope)
    if mapping.numeric:
        raise _error(
            f"mappings.{mapping.name} gives a number, not a name, so it goes after MAXIMIZE "
            "or MINIMIZE rather than in a set",
            call.pos,
        )
    namespace, items = _domain(mapping.value, scope.names, scope.dataset)
    return mapping, namespace, items


def _lookup(call: ast.Call, namespace: str, scope: _Scope) -> Item | ast.Selector:
    """What a call gives: the item its row names, or else the mapping's default phrase.

    A row naming somebody who is not working today names nobody the day has, and they are
    in no category, so the row is passed over for the default: a buddy who is resting is
    covered by whoever the default says, the same as a cabin with no buddy written down.
    """
    mapping, gives, allowed = _gives(call, scope)
    if namespace != gives:
        raise _error(
            f"expected a name from {namespace}, but mappings.{mapping.name} gives one from {gives}",
            call.pos,
        )
    key = _key(call.args, mapping, scope, call.pos)
    if key in mapping.rows:
        value = mapping.rows[key]
        item = date.fromisoformat(value) if gives == DATES else value
        if item in allowed:
            return item
    if mapping.default is None:
        raise _error(
            f"mappings.{mapping.name} has no row for {', '.join(key)}, and no default", call.pos
        )
    return _default(mapping.default)


def _default_scope(scope: "_Scope") -> "_Scope":
    """A default is written on the Mappings tab, where no variable of a request reaches."""
    return _Scope(scope.names, scope.dataset)


_default = cache(parse_default)


@cache
def _domain_expr(text: str) -> tuple[str, ast.SetExpr | None]:
    """A `keys` or `value` entry as its namespace and its set; a bare namespace has none."""
    if text.strip().lower() in KEY_NAMESPACES:
        return text.strip().lower(), None
    expr = parse_domain(text)
    if _needs_request(expr):
        raise ast.SkedgeError(
            f"'{text}' should be a namespace, such as staff, or a set of names, such as "
            "{staff.all - staff.counselor}",
            1,
            1,
        )
    namespace = _namespace_of(expr, None)
    if namespace not in KEY_NAMESPACES:
        raise ast.SkedgeError(
            f"'{text}' names {namespace}; a mapping takes and gives names from "
            f"{', '.join(KEY_NAMESPACES)}",
            1,
            1,
        )
    return namespace, expr


def _needs_request(expr: ast.SetExpr) -> bool:
    """Whether a set leans on something only a request can supply: a variable or a call."""
    return any(isinstance(node, ast.Var | ast.Call) for node in ast.nodes(expr))


def _domain(text: str, names: "_Names", dataset: Dataset) -> tuple[str, frozenset[Item]]:
    """What a `keys` or `value` entry stands for, worked out once for all the calls to it."""
    if text not in names.domains:
        namespace, expr = _domain_expr(text)
        if expr is None:
            spaces = names.spaces[namespace].values()
            names.domains[text] = namespace, frozenset().union(*(n.items for n in spaces))
        else:
            names.domains[text] = namespace, _evaluate(expr, namespace, _Scope(names, dataset))[0]
    return names.domains[text]


def domain_namespace(text: str) -> str:
    """The namespace a Mappings tab `keys` or `value` entry names. Raises SkedgeError."""
    return _domain_expr(text)[0]


class Domains:
    """What the Mappings tab's entries stand for on one day, each worked out once."""

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.names = _names(dataset)

    def of(self, text: str) -> tuple[str, frozenset[Item]]:
        """A `keys` or `value` entry, as its namespace and its items. Raises SkedgeError."""
        return _domain(text, self.names, self.dataset)

    def default(self, text: str) -> tuple[str, frozenset[Item]]:
        """A `default`, as the namespace and the items it chooses from.

        Raises SkedgeError for a phrase a default cannot be: one with a variable in it,
        which nothing on the Mappings tab can bind; an EACH, which would make one call
        many; and a set of several names with no quantifier to say how they are taken.
        """
        selector = _default(text)
        if selector.quantifier in (ast.EACH, ast.ANY):
            raise _error(
                f"a default is one choice, so it takes ALL or a count, not {selector.quantifier}",
                selector.pos,
            )
        if _needs_request(selector.expr):
            raise _error("a default names names, not variables or mappings", selector.pos)
        namespace = _namespace_of(selector.expr, None)
        items, single = _evaluate(selector.expr, namespace, _Scope(self.names, self.dataset))
        if not single and selector.quantifier is None:
            raise _error("a default of more than one name needs ALL or a count", selector.pos)
        return namespace, items


def judged(item: Item, namespace: str, dataset: Dataset) -> bool:
    """Whether today can say if an item belongs to a set. Of a person not working, it cannot.

    A category holds only the staff working today, so somebody resting all day or away is
    in none of them, and their being outside `staff.counselor` says nothing about whether
    they are a counselor. Everything else is in its sets whatever the day.
    """
    return namespace != STAFF or item in dataset.staff_categories.get(ALL_NAME, dataset.staff)


# -- selectors and sets -----------------------------------------------------------------------


def _choice(
    selector: ast.Selector,
    namespace: str,
    scope: _Scope,
    pool: bool,
    when: tuple[Item, ...] = (),
) -> Choice:
    """A selector as a Choice.

    With `pool`, the set is matched, right of NOT or in a score: it is a POOL, or ALL of
    them together right of NOT. Otherwise ANY pools it, a count counts it and ALL takes it
    whole.
    """
    if selector.quantifier == ast.EACH:
        item = scope.each[selector.pos]
        if isinstance(item, _Unit):
            return _group(item.group, namespace, scope, pool, when)
        if namespace == ACTIVITIES and not _on_those_days(frozenset({item}), True, when, scope)[0]:
            raise _AnotherDay
        return Choice((item,), POOL if pool else ALL, pos=selector.pos)
    expr = selector.expr
    if isinstance(expr, ast.Call) and selector.quantifier is None:
        # A call standing on its own is its row's one item, or else its default as written,
        # quantifier and all: a cabin with no buddy is covered by AT_LEAST 1 {staff.office}.
        found = _lookup(expr, namespace, scope)
        if isinstance(found, ast.Selector):
            default = _choice(found, namespace, _default_scope(scope), pool, when)
            return replace(default, pos=selector.pos)
    joined, bound = _split(selector.expr, scope)
    if bound:
        return _with_bound(selector, joined, bound, namespace, scope, pool, when)
    if isinstance(expr, ast.Var) and expr.name in scope.anys:
        if selector.quantifier:
            raise _error(
                f"'{expr.name}' is chosen by its binding and takes no quantifier", expr.pos
            )
        choice, bound = scope.anys[expr.name]
        _expect(namespace, bound, expr)
        return replace(choice, kind=POOL if pool else ANY, pos=selector.pos)
    items, single = _evaluate(expr, namespace, scope)
    one = single or isinstance(expr, ast.Call)  # before a season's cabin act comes to a day's
    if namespace == DATES:
        items = frozenset(d for d in items if d in scope.dataset.calendar)
    if namespace == ACTIVITIES:
        items, single = _on_those_days(items, single, when, scope)
        if not items and isinstance(expr, ast.Var):
            raise _AnotherDay  # a name EACH bound to an act on another day
    if pool:
        _matched(selector, one)
        # ALL is only matched right of NOT, where it is all of them together
        kind = ALL if selector.quantifier == ast.ALL else POOL
        return Choice(_sorted(items), kind, pos=selector.pos)
    if selector.quantifier is None:
        if not single:
            raise _error("needs a quantifier: ALL, ANY, EACH or a count", selector.pos)
        return Choice(_sorted(items), ALL, pos=selector.pos)
    if selector.quantifier == ast.COUNT and single and not isinstance(expr, ast.Call):
        if selector.n == 1:  # one of one: the item itself, weighed by a PREFER
            return Choice(_sorted(items), COUNT, 1, pos=selector.pos, bound=selector.bound)
        raise _error(
            f"a count counts the members of a set, and {ast.spoken(expr)} is one; put the "
            f"count on the set it counts, such as DURING {ast.worded(selector.bound, selector.n)} "
            "blocks.all",
            selector.pos,
        )
    _no_quantifier_on_one(expr, single, selector.pos)
    if selector.quantifier == ast.ALL:
        return Choice(_sorted(items), ALL, pos=selector.pos)
    if selector.quantifier == ast.ANY:
        return Choice(_sorted(items), POOL, pos=selector.pos)
    return Choice(_sorted(items), COUNT, selector.n, pos=selector.pos, bound=selector.bound)


_CHOSEN = (
    "left of NOT the subject is who the NOT is about, so it takes ALL, EACH or AT_LEAST n, not ANY"
)


def _matched(selector: ast.Selector, one: bool) -> None:
    """A set that is matched says so with ANY; one thing is written on its own.

    Whether a name is one thing is asked of the name, not of the day: a cabin's act all
    season, `activities.cabin_acts.p4`, is a set even on a day it comes to one act, so a
    request says the same about it whichever day it is read on.
    """
    if selector.quantifier is None and not one:
        raise _error(
            "a set here is matched, so it takes ANY: write ANY in front of it", selector.pos
        )
    if selector.quantifier in (ast.ANY, ast.ALL) and one:
        raise _error("is one item and takes no quantifier", selector.pos)


def _no_quantifier_on_one(expr: ast.SetExpr, single: bool, pos: ast.Pos) -> None:
    """A name that is one item takes no quantifier; a call may.

    A call's row is one item, but its default can be a choice, and which of the two a call
    comes to changes from day to day.
    """
    if single and not isinstance(expr, ast.Call):
        raise _error("is one item and takes no quantifier", pos)


def _split(expr: ast.SetExpr, scope: _Scope) -> tuple[ast.SetExpr | None, tuple]:
    """Separate the groups and the names the solver chooses from the rest of a `+` union.

    Only `+` is taken apart. `-` and `&` ask what a chosen name is *not*, or what it has in
    common with something, neither of which can be answered before the solver has chosen.
    """
    if isinstance(expr, ast.Group) or (isinstance(expr, ast.Var) and expr.name in scope.anys):
        return None, (expr,)
    if not isinstance(expr, ast.SetOp) or expr.op != "+":
        return expr, ()
    left, left_bound = _split(expr.left, scope)
    right, right_bound = _split(expr.right, scope)
    bound = left_bound + right_bound
    if not bound:
        return expr, ()
    if left is None:
        return right, bound
    if right is None:
        return left, bound
    return replace(expr, left=left, right=right), bound


def _with_bound(
    selector: ast.Selector,
    joined: ast.SetExpr | None,
    bound: tuple,
    namespace: str,
    scope: _Scope,
    pool: bool,
    when: tuple[Item, ...],
) -> Choice:
    """A set holding groups or bound names: the rest of it, plus what each of them brings.

    Taken whole, everything named is included, a bound name brings the one its binding
    picked and a group what it takes. Counted, each group is one of the things
    chosen from. A bound name cannot be: it is chosen once for the whole request, so
    choosing it again here would be choosing out of something still being chosen.
    """
    variables = [x for x in bound if isinstance(x, ast.Var)]
    if pool and selector.quantifier == ast.ALL:
        raise _error("ALL right of NOT takes names, not groups or chosen names", selector.pos)
    if pool:
        _matched(selector, False)
    elif selector.quantifier == ast.ANY:
        raise _error("ANY pools names, not groups or chosen names", selector.pos)
    if selector.quantifier not in (None, ast.ALL, ast.ANY) and variables:
        raise _error(
            "a set holding a name the solver chooses is taken with ALL or not at all",
            selector.pos,
        )
    parts = []
    for var in variables:
        choice, from_namespace = scope.anys[var.name]
        _expect(namespace, from_namespace, var)
        parts.append(replace(choice, kind=POOL if pool else ANY, pos=var.pos))
    groups = [_group(g, namespace, scope, pool, when) for g in bound if isinstance(g, ast.Group)]
    if joined is None and not groups:
        first, *rest = parts  # a bound name on its own, with any others added to it
        return replace(first, parts=tuple(rest), pos=selector.pos)
    items: frozenset[Item] = frozenset()
    if joined is not None:
        items, _ = _evaluate(joined, namespace, scope)
        if namespace == DATES:
            items = frozenset(d for d in items if d in scope.dataset.calendar)
        if namespace == ACTIVITIES:
            items, _ = _on_those_days(items, False, when, scope)
    if selector.quantifier == ast.COUNT and not pool:
        return Choice(
            _sorted(items),
            COUNT,
            selector.n,
            units=tuple(groups),
            pos=selector.pos,
            bound=selector.bound,
        )
    # taken whole, a group taking all of its set is only more of the same set
    for group in groups:
        if group.kind == ANY:
            parts.append(group)
        else:
            items |= frozenset(group.items)
            parts.extend(group.parts)
    kind = POOL if pool else ALL
    return Choice(_sorted(items), kind, parts=tuple(parts), pos=selector.pos)


def _group(
    group: ast.Group, namespace: str, scope: _Scope, pool: bool, when: tuple[Item, ...]
) -> Choice:
    """`(ALL s)` or `(AT_LEAST n s)`, as the choice it is wherever it stands.

    `(AT_LEAST n s)` chooses n of s, which brings them. In a pool only `(ALL s)` can
    stand, which the parser has seen to, and it is only more of the pool.
    """
    selector = ast.Selector(group.expr, group.quantifier, group.n, None, group.pos)
    selector = replace(selector, bound=group.bound)
    choice = _choice(selector, namespace, scope, pool, when)
    if pool:
        return replace(choice, kind=POOL)
    return replace(choice, kind=ANY, bound=None) if choice.kind == COUNT else choice


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
            raise _error(
                f"'{expr.name}' is chosen by the solver, so it can only be added to a set "
                "with '+', not taken away from one or crossed with one",
                expr.pos,
            )
        raise _error(f"unknown variable '{expr.name}'", expr.pos)
    if isinstance(expr, ast.Group):
        if expr.quantifier == ast.COUNT:
            raise _error(
                f"{ast.spoken(expr)} is chosen by the solver, so it can only be added to a set "
                "with '+', not taken away from one or crossed with one",
                expr.pos,
            )
        return _evaluate(expr.expr, namespace, scope)[0], False
    if isinstance(expr, ast.Call):
        return _call_items(expr, namespace, scope)
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


def _call_items(call: ast.Call, namespace: str, scope: _Scope) -> tuple[frozenset[Item], bool]:
    """A call inside a set, or after a quantifier: what it gives, as a set.

    A default that is a choice cannot be one. `{staff.office - mappings.buddy(c)}` asks who
    is left once the buddy is taken out, and while the buddy is still the solver's to pick
    from a set, nobody can say.
    """
    found = _lookup(call, namespace, scope)
    if not isinstance(found, ast.Selector):
        return frozenset({found}), True
    if found.quantifier == ast.COUNT:
        raise _error(
            f"mappings.{call.mapping.name} has no row for this, and its default is a choice "
            "the solver makes, which cannot stand where a set is wanted; write the call on "
            "its own, with no quantifier and nothing added to it or taken from it",
            call.pos,
        )
    items, single = _evaluate(found.expr, namespace, _default_scope(scope))
    return items, single and found.quantifier is None


def _one_date(expr: ast.SetExpr, scope: _Scope) -> date:
    items, single = _evaluate(expr, DATES, scope)
    if not single:
        raise _error("needs a single date here", expr.pos)
    return next(iter(items))


def _namespace_of(expr: ast.SetExpr, scope: _Scope | None) -> str:
    """The namespace a binding line's set belongs to, from the first name in it.

    Only a variable or a call needs the scope, so a set with neither is asked with None.
    """
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
    if isinstance(expr, ast.Group):
        return _namespace_of(expr.expr, scope)
    if isinstance(expr, ast.Call):
        return _gives(expr, scope)[1]
    return DATES


def _expect(namespace: str, actual: str, var: ast.Var) -> None:
    if namespace != actual:
        raise _error(f"expected a name from {namespace}, not '{var.name}'", var.pos)


def _sorted(items: frozenset[Item]) -> tuple[Item, ...]:
    return tuple(sorted(items, key=str))


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)
