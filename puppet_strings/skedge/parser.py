"""Text to syntax tree, using the Lark grammar in grammar.lark."""

from dataclasses import replace
from datetime import date
from pathlib import Path

from lark import Lark, Token, Transformer, UnexpectedInput, v_args
from lark.exceptions import VisitError

from puppet_strings.skedge import ast

_GRAMMAR = (Path(__file__).parent / "grammar.lark").read_text()
_parser = Lark(
    _GRAMMAR,
    parser="lalr",
    propagate_positions=True,
    start=["start", "mapping_domain", "mapping_default"],
)


def parse(text: str) -> ast.Declaration:
    """Parse Skedge text. Raises SkedgeError with the position of the first problem."""
    return _parse(text, "start")


def parse_domain(text: str) -> ast.SetExpr:
    """A Mappings tab `keys` or `value` entry: a set, with or without its braces."""
    return _parse(text, "mapping_domain")


def parse_default(text: str) -> ast.Selector:
    """A Mappings tab `default`: a set to take, with the quantifier to take it by."""
    return _parse(text, "mapping_default")


def _parse(text: str, start: str):
    try:
        tree = _parser.parse(text, start=start)
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
    "NAME": "a variable or label",
    "REF": "a name",
    "DATE": "a date",
    "DURATION": "a duration",
    "STRING": "'a quoted task'",
    "INT": "a number",
    "LBRACE": "{",
    "RBRACE": "}",
    "LPAR": "(",
    "RPAR": ")",
    "COMMA": ",",
    "COLON": ":",
    "_NL": "a new line",
    "$END": "end of text",
    "BOUND": "AT_LEAST, AT_MOST or EXACTLY",
    "ANY_N_OF": "ANY_n_OF",
    "SETOP": "+, - or &",
    "OFFSET": "a day offset such as - 6d",
}


MINUTES_IN = {"m": 1, "h": 60, "d": 60 * 24}


def parse_duration(text: str) -> int:
    """`30m`, `2h`, `1.5h`, `2d` -> minutes."""
    number, unit = float(text[:-1]), text[-1]
    minutes = number * MINUTES_IN[unit]
    if minutes != int(minutes):
        raise ValueError(f"duration '{text}' is not a whole number of minutes")
    return int(minutes)


def _pos(meta) -> ast.Pos:
    return ast.Pos(meta.line, meta.column)


def _token_pos(token: Token) -> ast.Pos:
    return ast.Pos(token.line, token.column)


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)


def _atom(item) -> ast.SetExpr:
    """A set expression: tokens become nodes, nodes pass through."""
    if not isinstance(item, Token):
        return item
    if item.type == "REF":
        namespace, name = str(item).split(".", 1)
        return ast.Ref(namespace, name, _token_pos(item))
    if item.type == "DATE":
        try:
            return ast.DateLiteral(date.fromisoformat(str(item)), _token_pos(item))
        except ValueError as e:
            raise ast.SkedgeError(f"invalid date '{item}'", item.line, item.column) from e
    return ast.Var(str(item), _token_pos(item))


def _quantifier(token: Token) -> tuple[str, int | None]:
    """The quantifier a token stands for, in the one case the tree holds it in.

    A keyword may be written in either case, so what the token says is upper-cased before
    anything is compared with it: `each_of` and `EACH_OF` are the same quantifier.
    """
    if token.type == "ANY_N_OF":
        return ast.ANY_OF, int(str(token)[len("ANY_") : -len("_OF")])
    return str(token).upper(), None


def _duration(token: Token) -> int:
    try:
        return parse_duration(str(token))
    except ValueError as e:
        raise ast.SkedgeError(str(e), token.line, token.column) from e


def _is(item, kind: str) -> bool:
    return isinstance(item, Token) and item.type == kind


@v_args(meta=True)
class _Builder(Transformer):
    """Turns the Lark tree into ast nodes."""

    def start(self, meta, lines):
        return ast.Declaration(tuple(lines))

    # -- lines ------------------------------------------------------------------------------

    def binding(self, meta, items):
        quantifier, name, expr = items
        kind, n = _quantifier(quantifier)
        selector = ast.Selector(_atom(expr), kind, n, str(name), _pos(meta))
        return ast.Binding(selector, _pos(meta))

    def if_(self, meta, items):
        return ast.Condition(False, _test(items[0]), _pos(meta))

    def unless(self, meta, items):
        return ast.Condition(True, _test(items[0]), _pos(meta))

    def junction(self, meta, items):
        test = items[0]
        if len(items) == 1:
            return ast.Condition(False, test, test.pos)
        ops = items[1::2]
        for op in ops:
            if str(op).upper() != str(ops[0]).upper():
                raise ast.SkedgeError("mixed AND and OR need parentheses", op.line, op.column)
        junction = ast.Junction(
            ops[0].type == "AND", tuple(_test(x) for x in items[::2]), _pos(meta)
        )
        return ast.Condition(False, junction, _pos(meta))

    def test(self, meta, items):
        amount = items[0] if isinstance(items[0], ast.Amount) else None
        pattern = next(x for x in items if isinstance(x, ast.Pattern))
        return ast.Predicate(amount, pattern, _is(items[-1], "CONSECUTIVE"), _pos(meta))

    def labeled(self, meta, items):
        name, statement = items
        return replace(statement, label=str(name))

    def gap(self, meta, items):
        first, second, amount = items
        return ast.Gap(str(first), str(second), amount, _pos(meta))

    # -- statements -------------------------------------------------------------------------

    def request_do(self, meta, items):
        who, what, *clauses = items
        return ast.Requirement(who, _target(what), False, tuple(clauses), _pos(meta))

    def request_activity(self, meta, items):
        """`REQUEST <activity>`: the activity happens, and its own positions say who by."""
        what, *clauses = items
        return ast.Requirement(None, _target(what), False, tuple(clauses), _pos(meta))

    def request_free(self, meta, items):
        who, _, *clauses = items
        return ast.Requirement(who, None, False, tuple(clauses), _pos(meta))

    def request_not_do(self, meta, items):
        who, what, *clauses = items
        return ast.Requirement(who, _target(what), True, tuple(clauses), _pos(meta))

    def request_not_free(self, meta, items):
        who, _, *clauses = items
        return ast.Requirement(who, None, True, tuple(clauses), _pos(meta))

    def exclude(self, meta, items):
        who, label, *clauses = items
        return ast.Exclude(who, str(label)[1:-1], tuple(clauses), _pos(meta))

    def request_count(self, meta, items):
        return self._count(meta, items, prefer=False)

    def prefer_count(self, meta, items):
        return self._count(meta, items, prefer=True)

    def _count(self, meta, items, prefer: bool):
        amount, pattern = items[0], items[1]
        return ast.Count(prefer, amount, pattern, _is(items[-1], "CONSECUTIVE"), _pos(meta))

    def prefer_score(self, meta, items):
        pattern, (maximize, call) = items
        return ast.Score(pattern, maximize, call.mapping, call.args, _pos(meta))

    def goal(self, meta, items):
        direction, call = items
        return direction.type == "MAXIMIZE", call

    def amount(self, meta, items):
        bound, value = items
        if value.type == "DURATION":
            return ast.Amount(str(bound).upper(), _duration(value), True, _pos(meta))
        return ast.Amount(str(bound).upper(), int(value), False, _pos(meta))

    # -- patterns ---------------------------------------------------------------------------

    def pattern_doing(self, meta, items):
        who, what, *clauses = items
        return ast.Pattern(who, _target(what), False, tuple(clauses), _pos(meta))

    def pattern_free(self, meta, items):
        who, _, *clauses = items
        return ast.Pattern(who, None, False, tuple(clauses), _pos(meta))

    def pattern_busy(self, meta, items):
        who, _, *clauses = items
        return ast.Pattern(who, None, True, tuple(clauses), _pos(meta))

    # -- selectors and clauses --------------------------------------------------------------

    def chooser(self, meta, items):
        return self._selector(meta, items)

    def pool(self, meta, items):
        return self._selector(meta, items)

    def _selector(self, meta, items):
        kind, n, var = None, None, None
        if _is(items[0], "ALL_OF") or _is(items[0], "ANY_N_OF") or _is(items[0], "EACH_OF"):
            kind, n = _quantifier(items[0])
            items = items[1:]
        if len(items) == 2:
            var = str(items[0])
            items = items[1:]
        return ast.Selector(_atom(items[0]), kind, n, var, _pos(meta))

    def during_c(self, meta, items):
        return ast.During(_pos(meta), items[0])

    def on_c(self, meta, items):
        return ast.On(_pos(meta), items[0])

    def as_role_c(self, meta, items):
        return ast.AsRole(_pos(meta), items[0])

    during = during_c
    on = on_c
    as_role = as_role_c

    def for_(self, meta, items):
        return ast.For(_pos(meta), _duration(items[0]))

    def company(self, meta, items):
        return self._selector(meta, items)

    def with_(self, meta, items):
        return ast.With(_pos(meta), items[0])

    def without(self, meta, items):
        return ast.Without(_pos(meta), items[0])

    # -- set expressions --------------------------------------------------------------------

    def call(self, meta, items):
        mapping, *args = items
        return ast.Call(_atom(mapping), tuple(_atom(a) for a in args), _pos(meta))

    def mapping_domain(self, meta, items):
        return _atom(items[0])

    def mapping_default(self, meta, items):
        return items[0]

    def setop(self, meta, items):
        result = _atom(items[0])
        ops = items[1::2]
        for op, right in zip(ops, items[2::2], strict=True):
            if str(op) != str(ops[0]):
                raise ast.SkedgeError("mixed set operators need parentheses", op.line, op.column)
            result = ast.SetOp(str(op), result, _atom(right), _pos(meta))
        return result

    def date_range(self, meta, items):
        return ast.DateRange(_atom(items[0]), _atom(items[1]), _pos(meta))

    def date_offset(self, meta, items):
        offset = str(items[1]).replace(" ", "").replace("\t", "")
        days = int(offset[1:-1])
        return ast.DateOffset(_atom(items[0]), days if offset[0] == "+" else -days, _pos(meta))


def _test(item) -> ast.Test:
    """A condition's test: what `junction` built, less the Condition it wrapped it in.

    A parenthesised condition is one term of the condition around it, so what the rule
    returns has to be unwrapped wherever it is used.
    """
    return item.test if isinstance(item, ast.Condition) else item


def _target(item) -> ast.Selector | ast.Task:
    if isinstance(item, Token):
        return ast.Task(str(item)[1:-1])
    return item
