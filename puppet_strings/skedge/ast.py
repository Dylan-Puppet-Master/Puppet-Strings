"""Syntax tree for a Skedge declaration, as produced by the parser."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date

from puppet_strings.skedge.namespaces import ACTIVITIES, BLOCKS, DATES, ROLES, STAFF

ALL = "ALL"
ANY_OF = "ANY_OF"
ANY = "ANY"  # with no number: any of these match, where a set is matched rather than chosen
EACH = "EACH"

AT_LEAST = "AT_LEAST"
AT_MOST = "AT_MOST"
EXACTLY = "EXACTLY"


class SkedgeError(Exception):
    """A parse or validation error with the position it was found at."""

    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"line {line}, column {column}: {message}")
        self.message = message
        self.line = line
        self.column = column


class NoSession(SkedgeError):
    """A `dates.session_target` name on a date that is in no session.

    The request is fine on the dates that are in one, so it is not wrong, only about
    nothing today: it is shown as invalid, and the solver leaves it out rather than stop.
    """


@dataclass(frozen=True)
class Pos:
    """Line and column of a node, 1-based."""

    line: int
    column: int


@dataclass(frozen=True)
class Ref:
    """A dotted name: `staff.rob`, `dates.session_mondays`."""

    namespace: str
    name: str
    pos: Pos


@dataclass(frozen=True)
class Var:
    """A bare identifier bound by `EACH x IN …`, `ANY n x IN …` or `x: …`."""

    name: str
    pos: Pos


@dataclass(frozen=True)
class DateLiteral:
    """`2026-09-14`."""

    value: date
    pos: Pos


@dataclass(frozen=True)
class DateOffset:
    """`dates.target - 6d`."""

    base: "SetExpr"
    days: int
    pos: Pos


@dataclass(frozen=True)
class DateRange:
    """`2026-09-14 .. 2026-09-18`, inclusive."""

    start: "SetExpr"
    end: "SetExpr"
    pos: Pos


@dataclass(frozen=True)
class SetOp:
    """`left + right`, `left - right`, `left & right`."""

    op: str
    left: "SetExpr"
    right: "SetExpr"
    pos: Pos


@dataclass(frozen=True)
class Call:
    """`mappings.buddy(c)`: what a mapping gives for these arguments, one per key."""

    mapping: Ref
    args: tuple["Var | Ref", ...]
    pos: Pos


@dataclass(frozen=True)
class Group:
    """`(ALL s)` or `(ANY n s)` inside a set: one part of it, taken the way it says.

    Added into a set taken whole, it brings its own members, all of them or the n chosen.
    Inside `ANY n` it is one of the things chosen from: `ANY 1 {staff.x + (ALL s)}` is
    x, or else everyone in s.
    """

    quantifier: str
    n: int | None
    expr: "SetExpr"
    pos: Pos


SetExpr = Ref | Var | DateLiteral | DateOffset | DateRange | SetOp | Call | Group


@dataclass(frozen=True)
class Selector:
    """A set with the quantifier written in front of it.

    `quantifier` is ALL, ANY_OF (with `n`), ANY (no `n`: matched, not chosen) or EACH,
    or None for one thing written on its own. `var` is the `x` of `EACH x IN s`.
    `consecutive` is `ANY [n] CONSECUTIVE`, which only a DURING takes: the parser moves it
    onto the During and refuses it anywhere else.
    """

    expr: SetExpr
    quantifier: str | None
    n: int | None
    var: str | None
    pos: Pos
    consecutive: bool = False


@dataclass(frozen=True)
class Task:
    """A quoted task with no positions or skills: `'archery maintenance'`."""

    text: str


Target = Selector | Task | None  # None is FREE


@dataclass(frozen=True)
class Clause:
    """Base for every clause on a statement."""

    pos: Pos


@dataclass(frozen=True)
class During(Clause):
    """`DURING <blocks>`, and with `consecutive`, `DURING ANY [n] CONSECUTIVE <blocks>`."""

    selector: Selector
    consecutive: bool = False


@dataclass(frozen=True)
class On(Clause):
    """`ON <dates>`."""

    selector: Selector


@dataclass(frozen=True)
class AsRole(Clause):
    """`AS_ROLE <roles>`."""

    selector: Selector


@dataclass(frozen=True)
class For(Clause):
    """`FOR <duration>`, in minutes."""

    minutes: int


@dataclass(frozen=True)
class With(Clause):
    """`WITH <staff>`: one name, or ALL or ANY n of a set."""

    selector: Selector


@dataclass(frozen=True)
class Without(Clause):
    """`WITHOUT <staff>`: not WITH the same."""

    selector: Selector


@dataclass(frozen=True)
class Amount:
    """`AT_LEAST 3`, `AT_MOST 2h`: a bound and a count or a duration in minutes."""

    bound: str
    value: int
    duration: bool
    pos: Pos


@dataclass(frozen=True)
class Pattern:
    """`<who> DO <what> …`, `<who> FREE …` or `<who> NOT FREE …` (`busy`)."""

    who: Selector
    what: Target
    busy: bool
    clauses: tuple[Clause, ...]
    pos: Pos


@dataclass(frozen=True)
class Requirement:
    """`REQUEST <who> DO <what> …`, `… FREE …`, and with `negated`, `… NOT DO …`, `… NOT FREE …`.

    `who` is None for `REQUEST <activity>`, which names no one: the activity's own
    positions say who may hold it, so there is nothing left for the request to add.
    """

    who: Selector | None
    what: Target
    negated: bool
    clauses: tuple[Clause, ...]
    pos: Pos
    label: str | None = None


@dataclass(frozen=True)
class Count:
    """`REQUEST|PREFER <amount> <pattern>`, or with `after_do`, `<who> DO <amount> <what> …`.

    `consecutive` is the pattern's `DURING ANY CONSECUTIVE <blocks>`: the amount is
    measured over back-to-back blocks on one day.
    """

    prefer: bool
    amount: Amount
    pattern: Pattern
    consecutive: bool
    pos: Pos
    label: str | None = None
    after_do: bool = False


@dataclass(frozen=True)
class Score:
    """`PREFER <pattern> MAXIMIZE|MINIMIZE mappings.x(args)`, of a numeric mapping."""

    pattern: Pattern
    maximize: bool
    mapping: Ref
    args: tuple[Var | Ref, ...]
    pos: Pos


@dataclass(frozen=True)
class Exclude:
    """`EXCLUDE <who> DO '<label>' [DURING <blocks>] [ON <dates>]`.

    Nobody is being asked for anything: these people are not at camp for those blocks, and
    `label` is what the schedule says where their assignments would have been.
    """

    who: Selector
    label: str
    clauses: tuple[Clause, ...]
    pos: Pos


Statement = Requirement | Count | Score | Exclude


@dataclass(frozen=True)
class Binding:
    """`EACH x IN s` or `ANY n x IN s` on a line of its own, or `x: ANY n s`."""

    selector: Selector
    pos: Pos


@dataclass(frozen=True)
class Definition:
    """`x: <set>`: a name for a set.

    The parser writes the set in wherever the name is used and drops the line, so nothing
    after the parser ever sees one.
    """

    name: str
    expr: SetExpr
    pos: Pos


@dataclass(frozen=True)
class Predicate:
    """`[<amount>] <pattern>`, or `<who> DO <amount> <what> …`: one thing a condition asks about."""

    amount: Amount | None
    pattern: Pattern
    consecutive: bool
    pos: Pos
    after_do: bool = False


@dataclass(frozen=True)
class Junction:
    """`a AND b AND …` or, without `all`, `a OR b OR …`."""

    all: bool
    parts: tuple["Test", ...]
    pos: Pos


Test = Predicate | Junction


def predicates(test: Test) -> Iterator[Predicate]:
    """The predicates a test is made of, in source order."""
    if isinstance(test, Junction):
        for part in test.parts:
            yield from predicates(part)
    else:
        yield test


@dataclass(frozen=True)
class Condition:
    """`IF …` or, with `unless`, `UNLESS …`."""

    unless: bool
    test: Test
    pos: Pos


@dataclass(frozen=True)
class Gap:
    """`GAP <label> TO <label> <amount>`."""

    first: str
    second: str
    amount: Amount
    pos: Pos


Line = Binding | Condition | Statement | Gap


@dataclass(frozen=True)
class Declaration:
    """A whole `.skedge` text."""

    lines: tuple[Line, ...]

    @property
    def statements(self) -> tuple[Statement, ...]:
        """The REQUEST, PREFER and EXCLUDE lines."""
        return tuple(x for x in self.lines if isinstance(x, Requirement | Count | Score | Exclude))

    @property
    def exclusions(self) -> tuple["Exclude", ...]:
        """The EXCLUDE lines."""
        return tuple(x for x in self.lines if isinstance(x, Exclude))

    @property
    def bindings(self) -> tuple[Binding, ...]:
        """The binding lines."""
        return tuple(x for x in self.lines if isinstance(x, Binding))

    @property
    def conditions(self) -> tuple[Condition, ...]:
        """The IF and UNLESS lines."""
        return tuple(x for x in self.lines if isinstance(x, Condition))

    @property
    def gaps(self) -> tuple[Gap, ...]:
        """The GAP lines."""
        return tuple(x for x in self.lines if isinstance(x, Gap))


def clause(clauses: tuple[Clause, ...], kind: type) -> Clause | None:
    """The clause of this type among a statement's clauses, if any."""
    return next((c for c in clauses if isinstance(c, kind)), None)


def patterns(line: Line) -> tuple[Pattern, ...]:
    """The patterns a line contains."""
    if isinstance(line, Count | Score):
        return (line.pattern,)
    if isinstance(line, Condition):
        return tuple(p.pattern for p in predicates(line.test))
    return ()


NAMESPACES = {During: BLOCKS, On: DATES, AsRole: ROLES}


def selectors(line: Line) -> Iterator[tuple[str | None, Selector]]:
    """Every selector a line holds with its namespace, in source order.

    A binding line's namespace is None: it comes from the names in its set.
    """
    if isinstance(line, Binding):
        yield None, line.selector
        return
    for part in (line, *patterns(line)):
        if not isinstance(part, Requirement | Pattern | Exclude):
            continue
        if part.who is not None:
            yield STAFF, part.who
        if isinstance(getattr(part, "what", None), Selector):
            yield ACTIVITIES, part.what
        for c in part.clauses:
            if type(c) in NAMESPACES:
                yield NAMESPACES[type(c)], c.selector


def set_exprs(line: Line) -> Iterator[SetExpr]:
    """Every set expression a line holds, including WITH, WITHOUT and mapping arguments."""
    for _, selector in selectors(line):
        yield selector.expr
    for part in (line, *patterns(line)):
        if isinstance(part, Requirement | Pattern | Exclude):
            for c in part.clauses:
                if isinstance(c, With | Without):
                    yield c.selector.expr
    if isinstance(line, Score):
        yield from line.args


def nodes(expr: SetExpr) -> Iterator[SetExpr]:
    """An expression and every expression inside it, the left of each before the right."""
    yield expr
    if isinstance(expr, SetOp):
        yield from nodes(expr.left)
        yield from nodes(expr.right)
    elif isinstance(expr, DateRange):
        yield from nodes(expr.start)
        yield from nodes(expr.end)
    elif isinstance(expr, DateOffset):
        yield from nodes(expr.base)
    elif isinstance(expr, Call):
        for arg in expr.args:
            yield from nodes(arg)
    elif isinstance(expr, Group):
        yield from nodes(expr.expr)


def vars_in(expr: SetExpr) -> Iterator[Var]:
    """The variables an expression mentions."""
    return (node for node in nodes(expr) if isinstance(node, Var))


def groups_in(expr: SetExpr) -> Iterator[Group]:
    """The groups an expression holds, at any depth."""
    return (node for node in nodes(expr) if isinstance(node, Group))


def picks(expr: SetExpr) -> bool:
    """Whether an expression holds an `(ANY n …)` group, which the solver chooses from."""
    return any(group.quantifier == ANY_OF for group in groups_in(expr))


def chooses(selector: Selector) -> bool:
    """Whether a selector takes its set some way, ALL or ANY n, rather than matching it."""
    return selector.quantifier in (ALL, ANY_OF) or picks(selector.expr)


def substitute(node, found: Callable[[Var], SetExpr | None]):
    """A node with every variable `found` knows replaced by what it gives, all the way down."""
    if isinstance(node, Var):
        return found(node) or node
    if isinstance(node, tuple):
        new = tuple(substitute(x, found) for x in node)
        return node if all(a is b for a, b in zip(new, node, strict=True)) else new
    if is_dataclass(node) and not isinstance(node, Pos):
        changed = {}
        for f in fields(node):
            old = getattr(node, f.name)
            new = substitute(old, found)
            if new is not old:
                changed[f.name] = new
        return replace(node, **changed) if changed else node
    return node


def spoken(expr: SetExpr) -> str:
    """A set expression written out the way it would be typed."""
    if isinstance(expr, Ref):
        return f"{expr.namespace}.{expr.name}"
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, DateLiteral):
        return expr.value.isoformat()
    if isinstance(expr, DateOffset):
        sign = "+" if expr.days >= 0 else "-"
        return f"{spoken(expr.base)} {sign} {abs(expr.days)}d"
    if isinstance(expr, DateRange):
        return f"{{{spoken(expr.start)} .. {spoken(expr.end)}}}"
    if isinstance(expr, SetOp):
        return f"{{{spoken(expr.left)} {expr.op} {spoken(expr.right)}}}"
    if isinstance(expr, Call):
        return f"{spoken(expr.mapping)}({', '.join(spoken(a) for a in expr.args)})"
    quantifier = f"ANY {expr.n}" if expr.quantifier == ANY_OF else expr.quantifier
    return f"({quantifier} {spoken(expr.expr)})"
