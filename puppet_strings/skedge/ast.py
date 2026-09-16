"""Syntax tree for a Skedge declaration, as produced by the parser."""

from dataclasses import dataclass
from datetime import date

VERBS = ("TASK", "FORBID", "PREFER", "AVOID")


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
    """`namespace.name`."""

    namespace: str
    name: str
    pos: Pos


@dataclass(frozen=True)
class DateLiteral:
    """`2026-09-14`."""

    value: date
    pos: Pos


@dataclass(frozen=True)
class DateOffset:
    """`date.target - 6d`."""

    base: "Ref | DateLiteral"
    days: int
    pos: Pos


@dataclass(frozen=True)
class DateRange:
    """`2026-09-14 .. 2026-09-18`, inclusive."""

    start: "Ref | DateLiteral"
    end: "Ref | DateLiteral"
    pos: Pos


@dataclass(frozen=True)
class SetOp:
    """`left + right`, `left - right`, `left & right`."""

    op: str
    left: "SetExpr"
    right: "SetExpr"
    pos: Pos


SetExpr = Ref | DateLiteral | DateOffset | DateRange | SetOp


@dataclass(frozen=True)
class Or:
    """Alternatives: `a OR b`."""

    items: tuple["Expr", ...]
    pos: Pos


@dataclass(frozen=True)
class And:
    """Items that go together: `a AND b`."""

    items: tuple["Expr", ...]
    pos: Pos


Expr = SetExpr | Or | And


@dataclass(frozen=True)
class Quantifier:
    """`ANY`, `ALL`, `EACH`, or `n OF`."""

    kind: str
    n: int | None = None


@dataclass(frozen=True)
class Selector:
    """A quantified expression: the argument of ON, DURING, ACROSS, ROLE, or a verb."""

    quantifier: Quantifier | None
    expr: Expr
    pos: Pos


@dataclass(frozen=True)
class Clause:
    """Base for every clause on a line."""

    pos: Pos


@dataclass(frozen=True)
class On(Clause):
    """`ON <selector>`."""

    selector: Selector


@dataclass(frozen=True)
class During(Clause):
    """`DURING <selector>`."""

    selector: Selector


@dataclass(frozen=True)
class Across(Clause):
    """`ACROSS <selector>`."""

    selector: Selector


@dataclass(frozen=True)
class Role(Clause):
    """`ROLE <selector>`."""

    selector: Selector


@dataclass(frozen=True)
class AdHoc:
    """A quoted task with no positions or skills: `'archery maintenance'`."""

    text: str


@dataclass(frozen=True)
class Free:
    """The `FREE` target: no assignment at all."""


FREE = Free()


@dataclass(frozen=True)
class Verb(Clause):
    """`TASK|FORBID|PREFER|AVOID <target>`."""

    kind: str
    target: Selector | AdHoc | Free


@dataclass(frozen=True)
class For(Clause):
    """`FOR <duration> [CONTINUOUS]`, duration in minutes."""

    minutes: int
    continuous: bool


@dataclass(frozen=True)
class Label(Clause):
    """`AS <name>`."""

    name: str


@dataclass(frozen=True)
class MetricClause(Clause):
    """`~ metric.<name>`."""

    ref: Ref


@dataclass(frozen=True)
class Per(Clause):
    """`PER <fields> BEYOND <n>`."""

    fields: tuple[str, ...]
    beyond: int


@dataclass(frozen=True)
class Gap(Clause):
    """`GAP <label> <label> <comparison> <duration>`, duration in minutes."""

    first: str
    second: str
    comparison: str
    minutes: int


@dataclass(frozen=True)
class Line:
    """One line: its clauses in source order."""

    clauses: tuple[Clause, ...]
    pos: Pos


@dataclass(frozen=True)
class Declaration:
    """A whole `.skedge` text."""

    lines: tuple[Line, ...]
