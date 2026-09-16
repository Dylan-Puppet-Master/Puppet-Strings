"""Text to syntax tree, using the Lark grammar in grammar.lark."""

from datetime import date
from pathlib import Path

from lark import Lark, Token, Transformer, UnexpectedInput, v_args
from lark.exceptions import VisitError

from puppet_strings.skedge import ast

_GRAMMAR = (Path(__file__).parent / "grammar.lark").read_text()
_parser = Lark(_GRAMMAR, parser="lalr", propagate_positions=True)


def parse(text: str) -> ast.Declaration:
    """Parse Skedge text. Raises SkedgeError with the position of the first problem."""
    try:
        tree = _parser.parse(text)
    except UnexpectedInput as e:
        line, column = _position(e, text)
        raise ast.SkedgeError(_describe(e), line, column) from e
    try:
        return _Builder().transform(tree)
    except VisitError as e:
        raise e.orig_exc from None


def _position(error: UnexpectedInput, text: str) -> tuple[int, int]:
    """Where the error is; an unexpected end of text points just past the last character."""
    token = getattr(error, "token", None)
    if token is not None and token.type == "$END":
        lines = text.split("\n")
        return len(lines), len(lines[-1]) + 1
    return error.line, error.column


def _describe(error: UnexpectedInput) -> str:
    expected = getattr(error, "expected", None) or getattr(error, "allowed", None)
    if expected:
        names = sorted(_TERMINAL_NAMES.get(t, t) for t in expected)
        return f"unexpected input; expected one of {', '.join(names)}"
    return "unexpected input"


_TERMINAL_NAMES = {
    "NAME": "a name",
    "DATE": "a date",
    "DURATION": "a duration",
    "STRING": "'a quoted task'",
    "INT": "a number",
    "LBRACE": "{",
    "RBRACE": "}",
    "LPAR": "(",
    "RPAR": ")",
    "_NL": "a new line",
    "$END": "end of text",
    "TILDE": "~",
    "VERB": "TASK, FORBID, PREFER or AVOID",
    "SETOP": "+, - or &",
    "OFFSET": "a day offset such as - 6d",
    "COMPARISON": "<=, >= or ==",
}


def parse_duration(text: str) -> int:
    """`30m`, `2h`, `1.5h` -> minutes."""
    number, unit = float(text[:-1]), text[-1]
    minutes = number * 60 if unit == "h" else number
    if minutes != int(minutes):
        raise ValueError(f"duration '{text}' is not a whole number of minutes")
    return int(minutes)


def _pos(meta) -> ast.Pos:
    return ast.Pos(meta.line, meta.column)


def _token_pos(token: Token) -> ast.Pos:
    return ast.Pos(token.line, token.column)


@v_args(meta=True)
class _Builder(Transformer):
    """Turns the Lark tree into ast nodes."""

    def start(self, meta, lines):
        return ast.Declaration(tuple(lines))

    def line(self, meta, clauses):
        return ast.Line(tuple(clauses), _pos(meta))

    def on(self, meta, items):
        return ast.On(_pos(meta), items[0])

    def during(self, meta, items):
        return ast.During(_pos(meta), items[0])

    def across(self, meta, items):
        return ast.Across(_pos(meta), items[0])

    def role(self, meta, items):
        return ast.Role(_pos(meta), items[0])

    def verb(self, meta, items):
        kind, target = items
        if isinstance(target, Token):
            target = ast.FREE if target.type == "FREE" else ast.AdHoc(str(target)[1:-1])
        return ast.Verb(_pos(meta), str(kind), target)

    def for_(self, meta, items):
        try:
            minutes = parse_duration(str(items[0]))
        except ValueError as e:
            raise ast.SkedgeError(str(e), meta.line, meta.column) from e
        return ast.For(_pos(meta), minutes, len(items) > 1)

    def label(self, meta, items):
        return ast.Label(_pos(meta), str(items[0]))

    def metric(self, meta, items):
        return ast.MetricClause(_pos(meta), items[0])

    def per(self, meta, items):
        *fields, beyond = items
        return ast.Per(_pos(meta), tuple(str(f) for f in fields), int(beyond))

    def gap(self, meta, items):
        first, second, comparison, duration = items
        try:
            minutes = parse_duration(str(duration))
        except ValueError as e:
            raise ast.SkedgeError(str(e), meta.line, meta.column) from e
        return ast.Gap(_pos(meta), str(first), str(second), str(comparison), minutes)

    def selector(self, meta, items):
        quantifier = items[0] if isinstance(items[0], ast.Quantifier) else None
        return ast.Selector(quantifier, items[-1], _pos(meta))

    def quantifier(self, meta, items):
        if items[0].type == "INT":
            return ast.Quantifier("OF", int(items[0]))
        return ast.Quantifier(str(items[0]))

    def or_(self, meta, items):
        return items[0] if len(items) == 1 else ast.Or(tuple(items), _pos(meta))

    def and_(self, meta, items):
        return items[0] if len(items) == 1 else ast.And(tuple(items), _pos(meta))

    def setop(self, meta, items):
        result = items[0]
        for op, right in zip(items[1::2], items[2::2], strict=True):
            result = ast.SetOp(str(op), result, right, _pos(meta))
        return result

    def date_range(self, meta, items):
        return ast.DateRange(items[0], items[1], _pos(meta))

    def date_offset(self, meta, items):
        offset = str(items[1]).replace(" ", "").replace("\t", "")
        days = int(offset[1:-1])
        return ast.DateOffset(items[0], days if offset[0] == "+" else -days, _pos(meta))

    def date_literal(self, meta, items):
        return _date(items[0])

    def ref(self, meta, items):
        namespace, *rest = (str(t) for t in items)
        return ast.Ref(namespace, ".".join(rest), _pos(meta))


def _date(token: Token) -> ast.DateLiteral:
    try:
        return ast.DateLiteral(date.fromisoformat(str(token)), _token_pos(token))
    except ValueError as e:
        raise ast.SkedgeError(f"invalid date '{token}'", token.line, token.column) from e
