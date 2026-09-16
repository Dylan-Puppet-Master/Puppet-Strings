from datetime import date

import pytest

from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse, parse_duration
from puppet_strings.skedge.scope import scope
from tests.examples import EXAMPLES


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_every_example_parses_and_scopes(name):
    declaration = parse(EXAMPLES[name])
    assert declaration.lines
    scope(declaration)


def test_clauses_and_positions():
    declaration = parse(EXAMPLES["pin"])
    on, during, across, verb = (line.clauses[0] for line in declaration.lines)
    assert isinstance(on, ast.On) and on.selector.expr == ast.DateLiteral(
        date(2026, 9, 14), ast.Pos(1, 4)
    )
    assert isinstance(during, ast.During)
    assert during.selector.expr == ast.Ref("block", "clinic_2", ast.Pos(2, 8))
    assert isinstance(across, ast.Across)
    assert isinstance(verb, ast.Verb) and verb.kind == "TASK"
    role = declaration.lines[3].clauses[1]
    assert isinstance(role, ast.Role) and role.selector.expr.name == "first"


def test_targets():
    assert parse("DURING block.a\nTASK FREE").lines[1].clauses[0].target is ast.FREE
    verb = parse("DURING block.a\nTASK 'archery maintenance'").lines[1].clauses[0]
    assert verb.target == ast.AdHoc("archery maintenance")


def test_or_and_tree():
    expr = parse(EXAMPLES["alternative-groups"]).lines[2].clauses[0].selector.expr
    assert isinstance(expr, ast.Or)
    james, pair = expr.items
    assert james == ast.Ref("staff", "james", ast.Pos(3, 9))
    assert isinstance(pair, ast.And)
    assert [r.name for r in pair.items] == ["tryne", "paul"]


def test_set_operators_fold_left():
    expr = parse(EXAMPLES["breaks"]).lines[0].clauses[0].selector.expr
    assert isinstance(expr, ast.SetOp) and expr.op == "-"
    assert expr.right.name == "counselors"
    assert expr.left.op == "-" and expr.left.left.name == "all"


def test_dates_offsets_and_ranges():
    expr = parse(EXAMPLES["variety-week"]).lines[0].clauses[0].selector.expr
    assert isinstance(expr, ast.DateRange)
    assert expr.start == ast.DateOffset(ast.Ref("date", "target", ast.Pos(1, 4)), -6, ast.Pos(1, 4))
    assert expr.end.name == "target"
    plus = parse("ON 2026-09-14 +2d\nDURING block.a\nTASK FREE").lines[0].clauses[0]
    assert plus.selector.expr.days == 2


def test_quantifiers():
    selector = parse(EXAMPLES["breaks"]).lines[1].clauses[0].selector
    assert selector.quantifier == ast.Quantifier("OF", 3)
    assert parse(EXAMPLES["day-off"]).lines[1].clauses[0].selector.quantifier.kind == "ALL"
    assert parse(EXAMPLES["counselor-hours"]).lines[0].clauses[0].selector.quantifier.kind == "EACH"


def test_other_clauses():
    lines = parse(EXAMPLES["counselor-hours"]).lines
    assert lines[1].clauses[3] == ast.Label(ast.Pos(2, 72), "morning")
    assert lines[3].clauses[0] == ast.Gap(ast.Pos(4, 1), "morning", "afternoon", "<=", 300)
    per = parse(EXAMPLES["variety-week"]).lines[3].clauses[1]
    assert per == ast.Per(ast.Pos(4, 27), ("staff", "activity"), 1)
    for_ = parse(EXAMPLES["training"]).lines[3].clauses[2]
    assert for_ == ast.For(ast.Pos(4, 47), 120, True)
    metric = parse(EXAMPLES["enjoyment"]).lines[2].clauses[1]
    assert metric.ref.name == "enjoyment"


def test_comments_and_blank_lines():
    text = "\n# breaks\nDURING block.a  # inline\n\nTASK 'break'\n\n"
    assert len(parse(text).lines) == 2


@pytest.mark.parametrize(
    ("text", "minutes"), [("30m", 30), ("2h", 120), ("1.5h", 90), ("0.5h", 30)]
)
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


@pytest.mark.parametrize(
    ("text", "line", "column"),
    [
        ("DURING block.a\nTASK", 2, 5),
        ("ON 2026-13-01\nDURING block.a\nTASK FREE", 1, 4),
        ("DURING block.a\nTASK 'x' FOR 1.25m", 2, 10),
        ("DURING block.a\nTASK activity.x ROLE", 2, 21),
        ("DURING {block.a OR }\nTASK FREE", 1, 20),
    ],
)
def test_parse_errors_carry_positions(text, line, column):
    with pytest.raises(ast.SkedgeError) as info:
        parse(text)
    assert (info.value.line, info.value.column) == (line, column)
