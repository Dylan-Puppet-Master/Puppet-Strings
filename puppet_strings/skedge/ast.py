"""Syntax tree for a Skedge declaration, as produced by the parser."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date

from puppet_strings.skedge.namespaces import (
    ACTIVITIES,
    BLOCKS,
    DATES,
    OFFERINGS,
    ROLES,
    STAFF,
    written,
)

ALL = "ALL"
ANY = "ANY"  # any of these: the set is one pool
EACH = "EACH"
ANY_OF = "ANY_OF"  # ANY n: n of the set, the solver's choice, made once
COUNT = "COUNT"  # AT_LEAST, AT_MOST or EXACTLY n: how many of the set the rest holds for

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
    """A dotted name, `staff.rob` or `dates.session_4.week_2`, or a whole namespace, `staff`."""

    namespace: str
    name: str
    pos: Pos


@dataclass(frozen=True)
class Var:
    """A bare identifier bound by `EACH x IN …`, `EXACTLY n x IN …` or `x: …`."""

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
    """`(ALL s)` or `(AT_LEAST n s)` inside a set: one part of it, taken the way it says.

    Added into a set taken whole, it brings its own members, all of them or the n chosen.
    Inside a count it is one of the things counted: `AT_LEAST 1 {staff.x + (ALL s)}` is
    x, or else everyone in s.
    """

    quantifier: str
    n: int | None
    expr: "SetExpr"
    pos: Pos
    bound: str | None = None


SetExpr = Ref | Var | DateLiteral | DateOffset | DateRange | SetOp | Call | Group


@dataclass(frozen=True)
class Selector:
    """A set with the quantifier written in front of it.

    `quantifier` is ALL, ANY (a pool), ANY_OF (ANY n, a choice), EACH or COUNT (with
    `bound` and `n`), or None for
    one thing written on its own. `var` is the `x` of `EACH x IN s`. `consecutive` is
    `ANY CONSECUTIVE` or `<count> CONSECUTIVE`, which only a DURING takes: the parser moves
    it onto the During and refuses it anywhere else.
    """

    expr: SetExpr
    quantifier: str | None
    n: int | None
    var: str | None
    pos: Pos
    consecutive: bool = False
    bound: str | None = None


@dataclass(frozen=True)
class Task:
    """A quoted task with no positions or skills: `'archery maintenance'`."""

    text: str


Target = Selector | Task | None  # None is FREE, or BUSY where a `busy` says so


@dataclass(frozen=True)
class Clause:
    """Base for every clause on a statement."""

    pos: Pos


@dataclass(frozen=True)
class During(Clause):
    """`DURING <blocks>`, and with `consecutive`, `DURING ANY|<count> CONSECUTIVE <blocks>`."""

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
    """`FOR [AT_LEAST|AT_MOST|EXACTLY] <duration>`, in minutes; no bound is EXACTLY."""

    minutes: int
    bound: str | None = None


@dataclass(frozen=True)
class With(Clause):
    """`WITH <staff> [AS_ROLE <role>]`: one name, or ALL or a count of a set, in that role."""

    selector: Selector
    role: Selector | None = None


@dataclass(frozen=True)
class Without(Clause):
    """`WITHOUT <staff> [AS_ROLE <role>]`: not WITH the same."""

    selector: Selector
    role: Selector | None = None


@dataclass(frozen=True)
class Amount:
    """`AT_LEAST 3`, `AT_MOST 2h`: a bound and a count or a duration in minutes.

    A count is written in front of the set it counts, where it becomes the selector's; a
    duration is a GAP's, or a FOR's.
    """

    bound: str
    value: int
    duration: bool
    pos: Pos


@dataclass(frozen=True)
class Pattern:
    """`<who> DO <what> …`, `<who> FREE …` or `<who> BUSY …` (`busy`)."""

    who: Selector
    what: Target
    busy: bool
    clauses: tuple[Clause, ...]
    pos: Pos


@dataclass(frozen=True)
class Requirement:
    """`REQUEST <who> DO <what> …`, `… FREE …`, `… BUSY …`, and with `negated`, `… NOT DO …`.

    `who` is None for `REQUEST <activity>`, which names no one: the activity's own
    positions say who may hold it, so there is nothing left for the request to add.

    `when` is where every IF or UNLESS it is inside was written, outermost first, as it is
    on every statement: the statement is asked for only when all of them hold.
    """

    who: Selector | None
    what: Target
    negated: bool
    clauses: tuple[Clause, ...]
    pos: Pos
    label: str | None = None
    busy: bool = False
    when: tuple[Pos, ...] = ()


@dataclass(frozen=True)
class Preference:
    """`PREFER <statement>`, scored by how close it comes to its count or its FOR length."""

    pattern: Pattern
    pos: Pos
    when: tuple[Pos, ...] = ()


@dataclass(frozen=True)
class Score:
    """`PREFER <pattern> MAXIMIZE|MINIMIZE mappings.x(args)`, of a numeric mapping."""

    pattern: Pattern
    maximize: bool
    mapping: Ref
    args: tuple[Var | Ref, ...]
    pos: Pos
    when: tuple[Pos, ...] = ()


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
    when: tuple[Pos, ...] = ()


Statement = Requirement | Preference | Score | Exclude


@dataclass(frozen=True)
class Binding:
    """`EACH x IN s` or `EXACTLY n x IN s` on a line of its own, or `x: EXACTLY n s`."""

    selector: Selector
    pos: Pos


@dataclass(frozen=True)
class TaskName:
    """`x: '<task>'`: a name for a quoted task, written in after DO like a Definition's set."""

    name: str
    task: Task
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
    """`<pattern>`: one thing a condition asks about, counted where it says so."""

    pattern: Pattern
    pos: Pos


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
    """`IF … THEN {…}` or, with `unless`, `UNLESS … THEN {…}`.

    The block is not kept here: each statement in it names this condition by its `pos` in
    its own `when`, and the condition is a line of the declaration like the statements.
    """

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
        return tuple(
            x for x in self.lines if isinstance(x, Requirement | Preference | Score | Exclude)
        )

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
    if isinstance(line, Preference | Score):
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
            yield (OFFERINGS if offers(part.what.expr) else ACTIVITIES), part.what
        for c in part.clauses:
            if type(c) in NAMESPACES:
                yield NAMESPACES[type(c)], c.selector
            elif isinstance(c, With | Without) and c.role is not None:
                yield ROLES, c.role


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


def offers(expr: SetExpr) -> bool:
    """Whether an expression names offerings, which stand where an activity would."""
    return any(isinstance(node, Ref) and node.namespace == OFFERINGS for node in nodes(expr))


def vars_in(expr: SetExpr) -> Iterator[Var]:
    """The variables an expression mentions."""
    return (node for node in nodes(expr) if isinstance(node, Var))


def groups_in(expr: SetExpr) -> Iterator[Group]:
    """The groups an expression holds, at any depth."""
    return (node for node in nodes(expr) if isinstance(node, Group))


def picks(expr: SetExpr) -> bool:
    """Whether an expression holds an `ANY n` group, which the solver chooses from."""
    return any(group.quantifier == ANY_OF for group in groups_in(expr))


def counts(selector: Selector) -> bool:
    """Whether a selector counts its set."""
    return selector.quantifier == COUNT


def chooses(selector: Selector) -> bool:
    """Whether a selector chooses from its set, ANY n, or holds a group that does."""
    return selector.quantifier == ANY_OF or picks(selector.expr)


def worded(bound: str | None, n: int | None) -> str:
    """A count as it is written: `AT_LEAST 3`."""
    return f"{bound} {n}"


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
        return written(expr.namespace, expr.name)
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
    if expr.quantifier == ANY_OF:
        quantifier = f"ANY {expr.n}"
    elif expr.quantifier == COUNT:
        quantifier = worded(expr.bound, expr.n)
    else:
        quantifier = expr.quantifier
    return f"({quantifier} {spoken(expr.expr)})"
