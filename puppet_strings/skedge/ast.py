"""Syntax tree for a Skedge declaration, as produced by the parser."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from puppet_strings.skedge.namespaces import ACTIVITIES, BLOCKS, DATES, ROLES, STAFF

ALL_OF = "ALL_OF"
ANY_OF = "ANY_OF"
EACH_OF = "EACH_OF"

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


@dataclass(frozen=True)
class Pos:
    """Line and column of a node, 1-based."""

    line: int
    column: int


@dataclass(frozen=True)
class Ref:
    """A dotted name: `staff.rob`, `dates.session.mondays`."""

    namespace: str
    name: str
    pos: Pos


@dataclass(frozen=True)
class Var:
    """A bare identifier bound by `EACH_OF x IN …` or `ANY_n_OF x IN …`."""

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


SetExpr = Ref | Var | DateLiteral | DateOffset | DateRange | SetOp


@dataclass(frozen=True)
class Selector:
    """A set with the quantifier written in front of it.

    `quantifier` is ALL_OF, ANY_OF (with `n`) or EACH_OF, or None for a bare set. `var` is
    the `x` of `EACH_OF x IN s`.
    """

    expr: SetExpr
    quantifier: str | None
    n: int | None
    var: str | None
    pos: Pos


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
    """`DURING <blocks>`."""

    selector: Selector


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
    """`WITH <staff>`."""

    staff: SetExpr


@dataclass(frozen=True)
class Without(Clause):
    """`WITHOUT <staff>`."""

    staff: SetExpr


@dataclass(frozen=True)
class Amount:
    """`AT_LEAST 3`, `AT_MOST 2h`: a bound and a count or a duration in minutes."""

    bound: str
    value: int
    duration: bool
    pos: Pos


@dataclass(frozen=True)
class Pattern:
    """`<who> DOING <what> …`, `<who> FREE …` or `<who> NOT FREE …` (`busy`)."""

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
    """`REQUEST|PREFER <amount> <pattern> [CONSECUTIVE]`."""

    prefer: bool
    amount: Amount
    pattern: Pattern
    consecutive: bool
    pos: Pos
    label: str | None = None


@dataclass(frozen=True)
class Score:
    """`PREFER <pattern> MAXIMIZE|MINIMIZE metrics.x(args)`."""

    pattern: Pattern
    maximize: bool
    metric: Ref
    args: tuple[Var | Ref, ...]
    pos: Pos


Statement = Requirement | Count | Score


@dataclass(frozen=True)
class Binding:
    """`EACH_OF x IN s` or `ANY_n_OF x IN s` on a line of its own."""

    selector: Selector
    pos: Pos


@dataclass(frozen=True)
class Condition:
    """`IF …` or, with `unless`, `UNLESS …`."""

    unless: bool
    amount: Amount | None
    pattern: Pattern
    consecutive: bool
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
        """The REQUEST and PREFER lines."""
        return tuple(x for x in self.lines if isinstance(x, Requirement | Count | Score))

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
    if isinstance(line, Count | Score | Condition):
        return (line.pattern,)
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
        if not isinstance(part, Requirement | Pattern):
            continue
        if part.who is not None:
            yield STAFF, part.who
        if isinstance(part.what, Selector):
            yield ACTIVITIES, part.what
        for c in part.clauses:
            if type(c) in NAMESPACES:
                yield NAMESPACES[type(c)], c.selector


def set_exprs(line: Line) -> Iterator[SetExpr]:
    """Every set expression a line holds, including WITH, WITHOUT and metric arguments."""
    for _, selector in selectors(line):
        yield selector.expr
    for part in (line, *patterns(line)):
        if isinstance(part, Requirement | Pattern):
            for c in part.clauses:
                if isinstance(c, With | Without):
                    yield c.staff
    if isinstance(line, Score):
        yield from line.args


def vars_in(expr: SetExpr) -> Iterator[Var]:
    """The variables an expression mentions."""
    if isinstance(expr, Var):
        yield expr
    elif isinstance(expr, SetOp):
        yield from vars_in(expr.left)
        yield from vars_in(expr.right)
    elif isinstance(expr, DateRange):
        yield from vars_in(expr.start)
        yield from vars_in(expr.end)
    elif isinstance(expr, DateOffset):
        yield from vars_in(expr.base)
