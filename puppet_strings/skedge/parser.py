"""Text to syntax tree, using the Lark grammar in grammar.lark."""

from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

from lark import Lark, Token, Transformer, UnexpectedInput, v_args
from lark.exceptions import VisitError

from puppet_strings.skedge import ast

_GRAMMAR = (Path(__file__).parent / "grammar.lark").read_text()
_CACHE = Path("~/.config/puppet_strings/parser.cache").expanduser()


def _cache() -> str | bool:
    """Where to keep the parse tables, which take longer to build than the rest of startup.

    Lark checks the file against the grammar and throws it away if the grammar changed. It
    is a pickle, so it lives in the user's own folder rather than the shared temp folder,
    where anybody could leave one under the name Lark would look for.
    """
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return str(_CACHE)


_parser = Lark(
    _GRAMMAR,
    parser="lalr",
    propagate_positions=True,
    start=["start", "mapping_domain", "mapping_default"],
    cache=_cache(),
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


@lru_cache(maxsize=4096)
def _parse(text: str, start: str):
    """The tree for some text, kept: a tree is immutable, and the same text is parsed often.

    Loading the window reads each request twice over, the editor re-reads what is typed
    each time it stops, and the trainer checks two answers on every day they are about.
    """
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
        names = sorted({_TERMINAL_NAMES.get(t, t.lstrip("_")) for t in expected})
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
    "ANY": "ANY n",
    "ANY_N_OF": "ANY n",
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


@dataclass(frozen=True)
class _Any:
    """`ANY n`, as the `any_n` rule hands it on."""

    n: int


def _quantifier(item) -> tuple[str, int | None]:
    """The quantifier a token or an `ANY n` stands for.

    A keyword may be written in either case, so what the token says is upper-cased before
    anything is compared with it: `each_of` and `EACH_OF` are the same quantifier.
    """
    if isinstance(item, _Any):
        return ast.ANY_OF, item.n
    return str(item).upper(), None


def _is_quantifier(item) -> bool:
    return isinstance(item, _Any) or _is(item, "ALL_OF") or _is(item, "EACH_OF")


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
        declaration = _define(ast.Declaration(tuple(lines)))
        _check_pools(declaration)
        return declaration

    # -- lines ------------------------------------------------------------------------------

    def binding(self, meta, items):
        quantifier, name, expr = items
        kind, n = _quantifier(quantifier)
        selector = ast.Selector(_atom(expr), kind, n, str(name), _pos(meta))
        return ast.Binding(selector, _pos(meta))

    def define(self, meta, items):
        """`x: <set>` names a set; `x: ANY n <set>` and `x: EACH_OF <set>` bind x."""
        name, *quantifier, expr = items
        kind, n = _quantifier(quantifier[0]) if quantifier else (None, None)
        if kind in (ast.ANY_OF, ast.EACH_OF):
            selector = ast.Selector(_atom(expr), kind, n, str(name), _pos(meta))
            return ast.Binding(selector, _pos(meta))
        return ast.Definition(str(name), _atom(expr), _pos(meta))

    def any_n(self, meta, items):
        token = items[-1]
        if token.type == "ANY_N_OF":
            n = str(token)[len("ANY_") : -len("_OF")]
            raise _error(f"write ANY {n}, not {token}", _token_pos(token))
        if int(token) < 1:
            raise _error("ANY needs a number of 1 or more", _token_pos(token))
        return _Any(int(token))

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
        return ast.Predicate(amount, pattern, _consecutive(items), _pos(meta))

    def labeled(self, meta, items):
        name, statement = items
        return replace(statement, label=str(name))

    def gap(self, meta, items):
        first, second, amount = items
        return ast.Gap(str(first), str(second), amount, _pos(meta))

    # -- statements -------------------------------------------------------------------------

    def request_do(self, meta, items):
        (who, what), clauses = _phrases(items)
        return ast.Requirement(who, _target(what), False, clauses, _pos(meta))

    def request_activity(self, meta, items):
        """`REQUEST <activity>`: the activity happens, and its own positions say who by."""
        (what,), clauses = _phrases(items)
        return ast.Requirement(None, _target(what), False, clauses, _pos(meta))

    def request_free(self, meta, items):
        (who, _), clauses = _phrases(items)
        return ast.Requirement(who, None, False, clauses, _pos(meta))

    def request_not_do(self, meta, items):
        (who, what), clauses = _phrases(items)
        return ast.Requirement(who, _target(what), True, clauses, _pos(meta))

    def request_not_free(self, meta, items):
        (who, _), clauses = _phrases(items)
        return ast.Requirement(who, None, True, clauses, _pos(meta))

    def exclude(self, meta, items):
        (who, label), clauses = _phrases(items)
        return ast.Exclude(who, str(label)[1:-1], clauses, _pos(meta))

    def request_count(self, meta, items):
        return self._count(meta, items, prefer=False)

    def prefer_count(self, meta, items):
        return self._count(meta, items, prefer=True)

    def _count(self, meta, items, prefer: bool):
        amount = next(x for x in items if isinstance(x, ast.Amount))
        pattern = _with_clauses(items)
        return ast.Count(prefer, amount, pattern, _consecutive(items), _pos(meta))

    def prefer_score(self, meta, items):
        maximize, call = next(x for x in items if isinstance(x, tuple))
        pattern = _with_clauses(items)
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
        (who, what), clauses = _phrases(items)
        return ast.Pattern(who, _target(what), False, clauses, _pos(meta))

    def pattern_free(self, meta, items):
        (who, _), clauses = _phrases(items)
        return ast.Pattern(who, None, False, clauses, _pos(meta))

    def pattern_busy(self, meta, items):
        (who, _), clauses = _phrases(items)
        return ast.Pattern(who, None, True, clauses, _pos(meta))

    # -- selectors and clauses --------------------------------------------------------------

    def chooser(self, meta, items):
        kind, n, var = None, None, None
        if _is_quantifier(items[0]):
            kind, n = _quantifier(items[0])
            items = items[1:]
        if len(items) == 2:
            var = str(items[0])
            items = items[1:]
        return ast.Selector(_atom(items[0]), kind, n, var, _pos(meta))

    def during(self, meta, items):
        return ast.During(_pos(meta), items[0], _is(items[-1], "CONSECUTIVE"))

    def on(self, meta, items):
        return ast.On(_pos(meta), items[0])

    def as_role(self, meta, items):
        return ast.AsRole(_pos(meta), items[0])

    def for_(self, meta, items):
        return ast.For(_pos(meta), _duration(items[0]))

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

    def group(self, meta, items):
        quantifier, expr = items
        kind, n = _quantifier(quantifier)
        return ast.Group(kind, n, _atom(expr), _pos(meta))

    def date_range(self, meta, items):
        return ast.DateRange(_atom(items[0]), _atom(items[1]), _pos(meta))

    def date_offset(self, meta, items):
        offset = str(items[1]).replace(" ", "").replace("\t", "")
        days = int(offset[1:-1])
        return ast.DateOffset(_atom(items[0]), days if offset[0] == "+" else -days, _pos(meta))


def _consecutive(items) -> bool:
    """Whether an amount is measured in runs: `AT_LEAST 2 CONSECUTIVE <pattern>`."""
    return any(_is(x, "CONSECUTIVE") for x in items)


def _phrases(items) -> tuple[list, tuple[ast.Clause, ...]]:
    """A statement's subject, verb and object, and its clauses from wherever they were written."""
    core = [x for x in items if not isinstance(x, ast.Clause)]
    return core, tuple(x for x in items if isinstance(x, ast.Clause))


def _with_clauses(items) -> ast.Pattern:
    """The pattern of a PREFER or a count, with the clauses written around it added in.

    A clause written ahead of the amount, or on the far side of MAXIMIZE, is still about
    the assignments the pattern matches.
    """
    at = next(i for i, x in enumerate(items) if isinstance(x, ast.Pattern))
    pattern = items[at]
    before, after = _phrases(items[:at])[1], _phrases(items[at + 1 :])[1]
    if before or after:
        pattern = replace(pattern, clauses=before + pattern.clauses + after)
    return pattern


def _check_pools(declaration: ast.Declaration) -> None:
    """Right of NOT, and in a pattern, a set is matched rather than chosen.

    So nothing there takes ALL_OF or ANY n, nor holds an `(ANY n …)` group, and no DURING
    there chooses blocks in a row. Who is alongside is the exception: WITH and WITHOUT count
    company, and say how many. Checked once the definitions are written in, so a group that
    arrives by a name is caught the same as one written out.
    """
    for line in declaration.lines:
        negated = []
        if isinstance(line, ast.Requirement) and line.negated:
            negated = [line.what, *line.clauses]
        for part in negated:
            if isinstance(part, ast.During) and part.consecutive:
                raise _error(
                    "right of NOT there are no blocks to choose, so no CONSECUTIVE; to limit "
                    "a run, count it: AT_MOST 1 CONSECUTIVE <who> DO …",
                    part.pos,
                )
        parts = list(negated)
        for pattern in ast.patterns(line):
            parts += [pattern.who, pattern.what, *pattern.clauses]
        for part in parts:
            if isinstance(part, ast.During) and part.consecutive:
                raise _error(
                    "CONSECUTIVE goes after the amount: AT_LEAST 2 CONSECUTIVE …", part.pos
                )
            if isinstance(part, ast.With | ast.Without):
                continue
            selector = getattr(part, "selector", part)
            if isinstance(selector, ast.Selector) and ast.chooses(selector):
                raise _error(
                    "a set here is matched, not chosen, so it takes no ALL_OF or ANY n",
                    selector.pos,
                )


def _define(declaration: ast.Declaration) -> ast.Declaration:
    """Write every `x: <set>` into the places x is used, and drop the definitions.

    A definition may use one made before or after it, but not itself, and its name is
    nobody else's: not a variable's and not a label's.
    """
    written = [x for x in declaration.lines if isinstance(x, ast.Definition)]
    if not written:
        return declaration
    definitions: dict[str, ast.Definition] = {}
    taken = _names_taken(declaration)
    for line in written:
        if line.name in definitions or line.name in taken:
            raise _error(f"'{line.name}' is defined twice", line.pos)
        definitions[line.name] = line
    expanded: dict[str, ast.SetExpr] = {}

    def expand(name: str, trail: tuple[str, ...]) -> ast.SetExpr:
        if name in trail:
            raise _error(f"'{name}' is defined in terms of itself", definitions[name].pos)
        if name not in expanded:
            expanded[name] = ast.substitute(
                definitions[name].expr, lambda var: found(var, (*trail, name))
            )
        return expanded[name]

    def found(var: ast.Var, trail: tuple[str, ...]) -> ast.SetExpr | None:
        return expand(var.name, trail) if var.name in definitions else None

    for name in definitions:
        expand(name, ())  # a definition nothing uses is still checked for a loop
    lines = tuple(
        ast.substitute(line, lambda var: found(var, ()))
        for line in declaration.lines
        if not isinstance(line, ast.Definition)
    )
    return ast.Declaration(lines)


def _names_taken(declaration: ast.Declaration) -> set[str]:
    """Every variable and label a declaration makes, which no definition may also be."""
    taken = set()
    for line in declaration.lines:
        taken.add(getattr(line, "label", None))
        for _, selector in ast.selectors(line):
            taken.add(selector.var)
    return taken - {None}


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
