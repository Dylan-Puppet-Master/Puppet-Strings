from datetime import date

import pytest

from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse, parse_duration
from tests.examples import EXAMPLES


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_every_doc_example_parses(name):
    assert parse(EXAMPLES[name]).statements


def test_requirement_shape_and_positions():
    (st,) = parse(
        "REQUEST ALL_OF {staff.lucy + staff.tom} DO 'take out garbage' "
        "DURING ANY_1_OF block.all ON EACH_OF date.session.this.mondays"
    ).lines
    assert isinstance(st, ast.Requirement) and not st.negated and st.label is None
    assert st.who.quantifier == ast.ALL_OF and st.who.pos == ast.Pos(1, 9)
    assert isinstance(st.who.expr, ast.SetOp) and st.who.expr.op == "+"
    assert st.who.expr.left == ast.Ref("staff", "lucy", ast.Pos(1, 17))
    assert st.what == ast.Task("take out garbage")
    during = ast.clause(st.clauses, ast.During).selector
    assert (during.quantifier, during.n) == (ast.ANY_OF, 1)
    assert during.expr == ast.Ref("block", "all", ast.Pos(1, 79))
    on = ast.clause(st.clauses, ast.On).selector
    assert on.quantifier == ast.EACH_OF and on.var is None
    assert on.expr == ast.Ref("date", "session.this.mondays", ast.Pos(1, 100))


def test_negation_and_free():
    (forbid,) = parse(
        "REQUEST ANY_1_OF {staff.lucy + staff.tom} NOT DO 'break' WITHOUT staff.rob"
    ).lines
    assert forbid.negated and forbid.what == ast.Task("break")
    assert ast.clause(forbid.clauses, ast.Without).staff == ast.Ref("staff", "rob", ast.Pos(1, 66))
    (free,) = parse("REQUEST staff.dylan FREE DURING ALL_OF block.all ON 2026-09-16").lines
    assert free.what is None and not free.negated
    assert ast.clause(free.clauses, ast.On).selector.expr == ast.DateLiteral(
        date(2026, 9, 16), ast.Pos(1, 53)
    )
    (busy,) = parse("REQUEST EACH_OF staff.counselor NOT FREE DURING block.clinic_1").lines
    assert busy.what is None and busy.negated
    assert busy.who.quantifier == ast.EACH_OF


def test_amount_statements():
    (count,) = parse("REQUEST AT_MOST 2 staff.all DOING 'break' DURING EACH_OF block.all").lines
    assert isinstance(count, ast.Count) and not count.prefer and not count.consecutive
    assert count.amount == ast.Amount(ast.AT_MOST, 2, False, ast.Pos(1, 9))
    assert count.pattern.who.quantifier is None and count.pattern.what == ast.Task("break")
    (hours,) = parse(
        "PREFER AT_LEAST 2h staff.cam_vl DOING activity.candle_making "
        "AS_ROLE role.trainee ON {2026-09-14 .. 2026-09-18} CONSECUTIVE"
    ).lines
    assert hours.prefer and hours.consecutive
    assert hours.amount == ast.Amount(ast.AT_LEAST, 120, True, ast.Pos(1, 8))
    role = ast.clause(hours.pattern.clauses, ast.AsRole).selector.expr
    assert role == ast.Ref("role", "trainee", ast.Pos(1, 70))
    assert isinstance(ast.clause(hours.pattern.clauses, ast.On).selector.expr, ast.DateRange)


def test_metric_statement():
    (score,) = parse(
        "PREFER EACH_OF s IN staff.all DOING EACH_OF c IN activity.all "
        "MINIMIZE metric.preference(s, activity.riflery)"
    ).lines
    assert isinstance(score, ast.Score) and not score.maximize
    assert score.metric == ast.Ref("metric", "preference", ast.Pos(1, 72))
    assert score.args == (
        ast.Var("s", ast.Pos(1, 90)),
        ast.Ref("activity", "riflery", ast.Pos(1, 93)),
    )
    assert (score.pattern.who.quantifier, score.pattern.who.var) == (ast.EACH_OF, "s")
    assert score.pattern.what.var == "c"


def test_bindings_conditions_labels_and_gaps():
    lines = parse(
        "ANY_2_OF p IN staff.counselor\n"
        "UNLESS AT_LEAST 3 p DOING activity.all CONSECUTIVE\n"
        "first: REQUEST p DO 'campfire setup' DURING block.clinic_4\n"
        "last:  REQUEST p DO 'campfire teardown' DURING block.evening\n"
        "GAP first TO last AT_LEAST 0m\n"
        "IF staff.rob FREE"
    ).lines
    binding, unless, first, last, gap, if_ = lines
    assert isinstance(binding, ast.Binding)
    assert (binding.selector.quantifier, binding.selector.n, binding.selector.var) == (
        ast.ANY_OF,
        2,
        "p",
    )
    assert unless.unless and unless.consecutive and unless.amount.value == 3
    assert unless.pattern.who.expr == ast.Var("p", ast.Pos(2, 19))
    assert (first.label, last.label) == ("first", "last") and first.pos == ast.Pos(3, 8)
    assert gap == ast.Gap(
        "first", "last", ast.Amount(ast.AT_LEAST, 0, True, ast.Pos(5, 19)), ast.Pos(5, 1)
    )
    assert not if_.unless and if_.amount is None and if_.pattern.what is None


def test_set_expressions():
    (st,) = parse(
        "REQUEST staff.dylan DO 'x' DURING block.a ON ANY_1_OF {(date.target - 6d) .. date.target}"
    ).lines
    on = ast.clause(st.clauses, ast.On).selector.expr
    assert isinstance(on, ast.DateRange)
    assert on.start == ast.DateOffset(ast.Ref("date", "target", ast.Pos(1, 57)), -6, ast.Pos(1, 57))
    assert on.end.name == "target"
    (st,) = parse(
        "REQUEST EACH_OF {staff.all - staff.director - staff.counselor} DO 'x' DURING block.a"
    ).lines
    expr = st.who.expr
    assert expr.op == "-" and expr.right.name == "counselor"
    assert expr.left.op == "-" and expr.left.left.name == "all"
    (st,) = parse(
        "REQUEST EACH_OF {staff.all - (staff.counselor & staff.director)} DO 'x' DURING block.a"
    ).lines
    assert st.who.expr.right.op == "&"
    (st,) = parse("REQUEST staff.dylan DO 'x' DURING block.a ON {2026-09-14 +2d}").lines
    assert ast.clause(st.clauses, ast.On).selector.expr.days == 2


def test_comments_and_blank_lines():
    text = "\n# breaks\nREQUEST staff.a DO 'break' DURING block.a  # inline\n\nGAP x TO y AT_MOST 1h\n\n"
    assert len(parse(text).lines) == 2


@pytest.mark.parametrize(
    ("text", "minutes"), [("30m", 30), ("2h", 120), ("1.5h", 90), ("0.5h", 30)]
)
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


@pytest.mark.parametrize(
    ("text", "message", "line", "column"),
    [
        ("REQUEST staff.rob DO", "expected one of", 1, 21),
        ("REQUEST staff.rob DO 'x' DURING block.a ON 2026-13-01", "invalid date", 1, 44),
        ("REQUEST staff.rob DO 'x' FOR 1.25m DURING block.a", "whole number of minutes", 1, 30),
        ("PREFER staff.rob DO 'x' DURING block.a", "expected one of", 1, 18),
        ("REQUEST staff.rob NOT DO ANY_1_OF activity.all", "expected one of", 1, 26),
        ("morning: PREFER AT_MOST 1 staff.all DOING 'x'", "expected one of", 1, 10),
        ("REQUEST AT_MOST 1 staff.all CONSECUTIVE", "expected one of", 1, 29),
        ("PREFER staff.all DOING 'x' MAXIMIZE", "expected one of", 1, 36),
        (
            "REQUEST staff.rob DO 'x' DURING {block.a + block.b & block.c}",
            "mixed set operators",
            1,
            52,
        ),
        ("REQUEST staff.rob DO 'x' DURING {block.a +}\n", "expected one of", 1, 43),
    ],
)
def test_parse_errors_carry_positions(text, message, line, column):
    with pytest.raises(ast.SkedgeError) as info:
        parse(text)
    assert message in info.value.message
    assert (info.value.line, info.value.column) == (line, column)
