from datetime import date

import pytest

from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse, parse_default, parse_domain, parse_duration
from tests.examples import EXAMPLES


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_every_doc_example_parses(name):
    assert parse(EXAMPLES[name]).statements


def test_requirement_shape_and_positions():
    (st,) = parse(
        "REQUEST ALL_OF {staff.lucy + staff.tom} DO 'take out garbage' "
        "DURING ANY 1 blocks.all ON EACH_OF dates.session_1.mondays"
    ).lines
    assert isinstance(st, ast.Requirement) and not st.negated and st.label is None
    assert st.who.quantifier == ast.ALL_OF and st.who.pos == ast.Pos(1, 9)
    assert isinstance(st.who.expr, ast.SetOp) and st.who.expr.op == "+"
    assert st.who.expr.left == ast.Ref("staff", "lucy", ast.Pos(1, 17))
    assert st.what == ast.Task("take out garbage")
    during = ast.clause(st.clauses, ast.During).selector
    assert (during.quantifier, during.n) == (ast.ANY_OF, 1)
    assert during.expr == ast.Ref("blocks", "all", ast.Pos(1, 76))
    on = ast.clause(st.clauses, ast.On).selector
    assert on.quantifier == ast.EACH_OF and on.var is None
    assert on.expr == ast.Ref("dates", "session_1.mondays", ast.Pos(1, 98))


def test_negation_and_free():
    (forbid,) = parse(
        "REQUEST ANY 1 {staff.lucy + staff.tom} NOT DO 'break' WITHOUT staff.rob"
    ).lines
    assert forbid.negated and forbid.what == ast.Task("break")
    assert ast.clause(forbid.clauses, ast.Without).selector.expr == ast.Ref(
        "staff", "rob", ast.Pos(1, 63)
    )
    (free,) = parse("REQUEST staff.dylan FREE DURING ALL_OF blocks.all ON 2026-09-16").lines
    assert free.what is None and not free.negated
    assert ast.clause(free.clauses, ast.On).selector.expr == ast.DateLiteral(
        date(2026, 9, 16), ast.Pos(1, 54)
    )
    (busy,) = parse("REQUEST EACH_OF staff.counselor NOT FREE DURING blocks.clinic_1").lines
    assert busy.what is None and busy.negated
    assert busy.who.quantifier == ast.EACH_OF


def test_amount_statements():
    (count,) = parse("REQUEST AT_MOST 2 ANY staff.all DO 'break' DURING EACH_OF blocks.all").lines
    assert isinstance(count, ast.Count) and not count.prefer and not count.consecutive
    assert count.amount == ast.Amount(ast.AT_MOST, 2, False, ast.Pos(1, 9))
    assert count.pattern.who.quantifier == ast.ANY and count.pattern.what == ast.Task("break")
    (hours,) = parse(
        "PREFER AT_LEAST 2h staff.cam_vl DO activities.clinics.candle_making "
        "AS_ROLE roles.trainee ON {2026-09-14 .. 2026-09-18} DURING ANY CONSECUTIVE blocks.all"
    ).lines
    assert hours.prefer and hours.consecutive
    assert hours.amount == ast.Amount(ast.AT_LEAST, 120, True, ast.Pos(1, 8))
    role = ast.clause(hours.pattern.clauses, ast.AsRole).selector.expr
    assert role == ast.Ref("roles", "trainee", ast.Pos(1, 77))
    assert isinstance(ast.clause(hours.pattern.clauses, ast.On).selector.expr, ast.DateRange)


def test_mapping_statement():
    (score,) = parse(
        "PREFER EACH_OF s IN staff.all DO EACH_OF c IN activities.clinics.all "
        "MINIMIZE mappings.preference(s, activities.clinics.riflery)"
    ).lines
    assert isinstance(score, ast.Score) and not score.maximize
    assert score.mapping == ast.Ref("mappings", "preference", ast.Pos(1, 79))
    assert score.args == (
        ast.Var("s", ast.Pos(1, 99)),
        ast.Ref("activities", "clinics.riflery", ast.Pos(1, 102)),
    )
    assert (score.pattern.who.quantifier, score.pattern.who.var) == (ast.EACH_OF, "s")
    assert score.pattern.what.var == "c"


def test_a_mapping_call_is_a_set():
    (binding, request) = parse(
        "EACH_OF c IN staff.counselor\n"
        "REQUEST ALL_OF {staff.office - mappings.buddy(c)} FREE DURING blocks.evening"
    ).lines
    call = request.who.expr.right
    assert call == ast.Call(
        ast.Ref("mappings", "buddy", ast.Pos(2, 32)),
        (ast.Var("c", ast.Pos(2, 47)),),
        ast.Pos(2, 32),
    )


def test_mapping_cells_parse_on_their_own():
    for text in ("{staff.all - staff.counselor}", "staff.all - staff.counselor"):
        assert isinstance(parse_domain(text), ast.SetOp)  # the braces are optional
    default = parse_default("ANY 1 {staff.all - staff.counselor}")
    assert (default.quantifier, default.n) == (ast.ANY_OF, 1)


def test_bindings_conditions_labels_and_gaps():
    lines = parse(
        "ANY 2 p IN staff.counselor\n"
        "UNLESS p DO AT_LEAST 3 ANY activities.clinics.all DURING ANY CONSECUTIVE blocks.all\n"
        "first: REQUEST p DO 'campfire setup' DURING blocks.clinic_4\n"
        "last:  REQUEST p DO 'campfire teardown' DURING blocks.evening\n"
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
    assert unless.unless and unless.test.consecutive and unless.test.amount.value == 3
    assert unless.test.after_do and unless.test.pattern.who.expr == ast.Var("p", ast.Pos(2, 8))
    assert (first.label, last.label) == ("first", "last") and first.pos == ast.Pos(3, 8)
    assert gap == ast.Gap(
        "first", "last", ast.Amount(ast.AT_LEAST, 0, True, ast.Pos(5, 19)), ast.Pos(5, 1)
    )
    assert not if_.unless and if_.test.amount is None and if_.test.pattern.what is None


def test_conditions_join_with_and_and_or_over_several_lines():
    (if_, _) = parse(
        "IF\n"
        "AT_LEAST 2 ANY staff.counselor DO 'break' DURING ANY CONSECUTIVE blocks.all\n"
        "AND\n"
        "staff.dylan FREE DURING blocks.lunch\n"
        "REQUEST staff.rob DO 'x' DURING blocks.lunch"
    ).lines
    assert isinstance(if_.test, ast.Junction) and if_.test.all
    first, second = if_.test.parts
    assert first.consecutive and first.amount.value == 2 and second.pattern.what is None
    (unless, _) = parse(
        "UNLESS (ANY staff.a FREE and ANY staff.b FREE)\n"
        "OR staff.c FREE\n"
        "REQUEST staff.rob DO 'x' DURING blocks.lunch"
    ).lines
    assert unless.unless and not unless.test.all
    assert [type(p) for p in unless.test.parts] == [ast.Junction, ast.Predicate]
    assert len(list(ast.predicates(unless.test))) == 3


def test_mixing_and_with_or_needs_parentheses():
    with pytest.raises(ast.SkedgeError, match="mixed AND and OR need parentheses"):
        parse(
            "IF ANY staff.a FREE AND ANY staff.b FREE OR ANY staff.c FREE\nREQUEST staff.rob FREE"
        )


def test_set_expressions():
    (st,) = parse(
        "REQUEST staff.dylan DO 'x' DURING blocks.a ON ANY 1 {(dates.target - 6d) .. dates.target}"
    ).lines
    on = ast.clause(st.clauses, ast.On).selector.expr
    assert isinstance(on, ast.DateRange)
    assert on.start == ast.DateOffset(
        ast.Ref("dates", "target", ast.Pos(1, 55)), -6, ast.Pos(1, 55)
    )
    assert on.end.name == "target"
    (st,) = parse(
        "REQUEST EACH_OF {staff.all - staff.director - staff.counselor} DO 'x' DURING blocks.a"
    ).lines
    expr = st.who.expr
    assert expr.op == "-" and expr.right.name == "counselor"
    assert expr.left.op == "-" and expr.left.left.name == "all"
    (st,) = parse(
        "REQUEST EACH_OF {staff.all - (staff.counselor & staff.director)} DO 'x' DURING blocks.a"
    ).lines
    assert st.who.expr.right.op == "&"
    (st,) = parse("REQUEST staff.dylan DO 'x' DURING blocks.a ON {2026-09-14 +2d}").lines
    assert ast.clause(st.clauses, ast.On).selector.expr.days == 2


def test_comments_and_blank_lines():
    text = "\n# breaks\nREQUEST staff.a DO 'break' DURING blocks.a  # inline\n\nGAP x TO y AT_MOST 1h\n\n"
    assert len(parse(text).lines) == 2


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("30m", 30), ("2h", 120), ("1.5h", 90), ("0.5h", 30), ("1d", 1440), ("2d", 2880)],
)
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


def test_a_gap_may_be_written_in_days():
    """`48h` and `2d` are the same gap; days are how anybody says two nights apart."""
    text = (
        "first:  REQUEST staff.rob DO 'setup' FOR 1h DURING blocks.clinic_1\n"
        "second: REQUEST staff.rob DO 'strike' FOR 1h DURING blocks.clinic_2\n"
        "GAP first TO second AT_LEAST {amount}"
    )
    (days,) = parse(text.format(amount="2d")).gaps
    (hours,) = parse(text.format(amount="48h")).gaps
    assert days.amount == hours.amount
    assert days.amount.value == 2880 and days.amount.duration


def test_exclude_statement():
    (line,) = parse("EXCLUDE staff.dylan DO 'offsite' DURING ALL_OF blocks.all ON 2026-08-26").lines
    assert isinstance(line, ast.Exclude)
    assert line.who.expr == ast.Ref("staff", "dylan", ast.Pos(1, 9))
    assert line.label == "offsite"  # a label for the schedule, not an activity
    assert ast.clause(line.clauses, ast.During).selector.quantifier == ast.ALL_OF
    assert ast.clause(line.clauses, ast.On).selector.expr.value == date(2026, 8, 26)
    (bare,) = parse("EXCLUDE staff.dylan DO 'offsite'").lines  # every block of the day
    assert bare.clauses == ()


def test_a_keyword_may_be_written_in_either_case():
    """Upper case is the convention; lower case is the same request, not an error."""
    shouted = parse("REQUEST ALL_OF staff.counselor DO 'x' FOR 30m DURING ANY 1 blocks.all")
    quiet = parse("request all_of staff.counselor do 'x' for 30m during any 1 blocks.all")
    assert shouted == quiet
    (binding, line) = parse(
        "each_of c in staff.counselor\nrequest c not free during blocks.clinic_1"
    ).lines
    assert binding.selector.quantifier == ast.EACH_OF and line.negated
    (count,) = parse(
        "prefer at_most 2 any staff.all do 'break' during any consecutive blocks.all"
    ).lines
    assert count.amount.bound == ast.AT_MOST and count.consecutive


def test_consecutive_goes_on_the_blocks():
    """In a count the amount is measured in runs; after ANY n blocks, they adjoin."""
    (count,) = parse(
        "REQUEST AT_LEAST 2 staff.dylan DO 'x' DURING ANY CONSECUTIVE blocks.all"
    ).lines
    assert count.consecutive and ast.clause(count.pattern.clauses, ast.During).consecutive
    (run,) = parse("REQUEST staff.dylan DO 'x' DURING ANY 2 CONSECUTIVE blocks.all").lines
    during = ast.clause(run.clauses, ast.During)
    assert during.consecutive and during.selector.n == 2 and not during.selector.consecutive
    (plain,) = parse("REQUEST staff.dylan DO 'x' DURING ANY 2 blocks.all").lines
    assert not ast.clause(plain.clauses, ast.During).consecutive


def test_an_amount_may_follow_do():
    """`s DO AT_LEAST 3 …` counts the same as `AT_LEAST 3 s DO …`, and says it after DO."""
    after = "IF s DO AT_LEAST 3 ANY activities.clinics.all DURING ANY CONSECUTIVE blocks.all"
    before = "IF AT_LEAST 3 s DO ANY activities.clinics.all DURING ANY CONSECUTIVE blocks.all"
    tail = "\nREQUEST s FREE DURING ANY 1 blocks.all"
    (if_after, _), (if_before, _) = parse(after + tail).lines, parse(before + tail).lines
    assert if_after.test.after_do and not if_before.test.after_do
    assert if_after.test.amount.value == if_before.test.amount.value == 3
    assert if_after.test.consecutive and if_before.test.consecutive
    (count,) = parse("PREFER EACH_OF staff.all DO AT_MOST 8 ANY activities.clinics.all").lines
    assert count.prefer and count.after_do and count.amount.value == 8


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("REQUEST AT_LEAST 2 CONSECUTIVE staff.dylan DO 'x'", "CONSECUTIVE goes on the blocks"),
        (
            "IF AT_LEAST 2 CONSECUTIVE s DO 'x'\nREQUEST s FREE DURING blocks.lunch",
            "CONSECUTIVE goes on the blocks",
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING ANY 2 blocks.all CONSECUTIVE",
            "CONSECUTIVE goes before the blocks: DURING ANY 2 CONSECUTIVE blocks.all",
        ),
        ("REQUEST staff.dylan DO 'x' DURING ALL_OF CONSECUTIVE blocks.all", "after ANY or ANY n"),
        ("REQUEST staff.dylan DO 'x' ON ANY 2 CONSECUTIVE dates.season.all", "is about blocks"),
        (
            "IF staff.dylan DO ANY activities.clinics.all DURING ANY CONSECUTIVE blocks.all\nREQUEST staff.dylan FREE",
            "needs AT_LEAST",
        ),
        (
            "REQUEST AT_LEAST 2 staff.dylan DO 'x' DURING ANY 2 CONSECUTIVE blocks.all",
            "with no number",
        ),
        ("REQUEST ANY staff.all DO AT_MOST 2 'break'", "an amount after DO counts one person's"),
    ],
)
def test_consecutive_and_amounts_in_the_old_places_say_the_new_ones(text, message):
    with pytest.raises(ast.SkedgeError) as e:
        parse(text)
    assert message in e.value.message


def test_consecutive_right_of_not_says_to_count_the_run():
    """Right of NOT nothing is chosen, so the message points at the amount that limits runs."""
    with pytest.raises(ast.SkedgeError) as e:
        parse("REQUEST EACH_OF staff.all NOT DO 'break' DURING ANY 2 CONSECUTIVE blocks.all")
    assert e.value.message.startswith("right of NOT there are no blocks to choose")
    assert "DURING ANY CONSECUTIVE" in e.value.message


def test_a_name_that_starts_with_a_keyword_is_still_a_name():
    """`FOR` ends at a word boundary, so `format` is one word and not two."""
    (binding, _) = parse(
        "each_of format in staff.counselor\nrequest format do 'x' during blocks.a"
    ).lines
    assert binding.selector.var == "format"


def test_a_day_offset_is_still_an_offset_and_not_a_duration():
    """`- 6d` inside a set is an offset from a date; only the lexer tells them apart."""
    (line,) = parse("REQUEST staff.rob DO 'x' DURING blocks.a ON {dates.target - 6d}").lines
    assert line.clauses[1].selector.expr.days == -6


@pytest.mark.parametrize(
    ("text", "message", "line", "column"),
    [
        ("REQUEST staff.rob DO", "expected one of", 1, 21),
        ("REQUEST staff.rob DO 'x' DURING blocks.a ON 2026-13-01", "invalid date", 1, 45),
        ("REQUEST staff.rob DO 'x' FOR 1.25m DURING blocks.a", "whole number of minutes", 1, 30),
        # a PREFER with no amount is a score, so what is missing is the goal
        ("PREFER staff.rob DO 'x' DURING blocks.a", "expected one of", 1, 40),
        ("REQUEST staff.rob NOT DO ANY 1 activities.clinics.all", "right of NOT a set", 1, 26),
        ("morning: PREFER AT_MOST 1 ANY staff.all DO 'x'", "expected one of", 1, 10),
        ("REQUEST AT_MOST 1 staff.all CONSECUTIVE", "expected one of", 1, 29),
        ("PREFER staff.all DO 'x' MAXIMIZE", "expected one of", 1, 33),
        (
            "REQUEST staff.rob DO 'x' DURING {blocks.a + blocks.b & blocks.c}",
            "mixed set operators",
            1,
            54,
        ),
        ("REQUEST staff.rob DO 'x' DURING {blocks.a +}\n", "expected one of", 1, 44),
    ],
)
def test_parse_errors_carry_positions(text, message, line, column):
    with pytest.raises(ast.SkedgeError) as info:
        parse(text)
    assert message in info.value.message
    assert (info.value.line, info.value.column) == (line, column)


def test_clauses_go_anywhere_in_a_statement():
    """Only the subject, DO and the object keep their order; clauses go around them."""
    written = parse(
        "REQUEST\n"
        "ON ANY 1 {2026-08-04 .. 2026-08-07}  # a clause before the subject\n"
        "ALL_OF {x + staff.alesa}\n"
        "DO 'video'\n"
        "FOR 30m\n"
        "DURING ANY 1 blocks.all"
    ).lines[0]
    assert [type(c) for c in written.clauses] == [ast.On, ast.For, ast.During]
    assert written.who.quantifier == ast.ALL_OF and written.what == ast.Task("video")
    between = parse("REQUEST staff.rob DURING blocks.a DO 'x' ON dates.target").lines[0]
    assert [type(c) for c in between.clauses] == [ast.During, ast.On]
    (count,) = parse("REQUEST DURING blocks.lunch AT_MOST 2 ANY staff.all DO 'break'").lines
    assert ast.clause(count.pattern.clauses, ast.During) is not None
    (score,) = parse(
        "PREFER ANY staff.all DO ANY activities.clinics.all MAXIMIZE mappings.pref(s) DURING ANY blocks.a"
    ).lines
    assert ast.clause(score.pattern.clauses, ast.During) is not None


def test_a_line_that_cannot_start_a_statement_continues_the_one_above():
    lines = parse(
        "EACH_OF c IN staff.counselor\n"
        "REQUEST\n"
        "  staff.rob DO 'x'\n"
        "  DURING ANY 1 {blocks.a +\n"
        "  blocks.b}\n"
        "elves: {staff.emily + staff.tori}\n"
        "REQUEST elves DO 'y' DURING blocks.a"
    ).lines
    assert [type(x) for x in lines] == [ast.Binding, ast.Requirement, ast.Requirement]


def test_a_group_is_a_quantified_part_of_a_set():
    (st,) = parse(
        "REQUEST ALL_OF {staff.charlton + (ANY 1 {staff.dylan + staff.donny})} DO 'x' "
        "DURING blocks.a"
    ).lines
    group = st.who.expr.right
    assert isinstance(group, ast.Group) and (group.quantifier, group.n) == (ast.ANY_OF, 1)
    (st,) = parse(
        "REQUEST ANY 1 {staff.x + (ALL_OF {staff.y + staff.z})} DO 'x' DURING blocks.a"
    ).lines
    assert st.who.expr.right.quantifier == ast.ALL_OF


def test_a_definition_is_written_in_where_it_is_used():
    (st,) = parse(
        "office_elves: {staff.emily + staff.tori}\n"
        "REQUEST EACH_OF {staff.directors + office_elves} DO 'DYOW' DURING blocks.a"
    ).lines
    assert ast.spoken(st.who.expr.right) == "{staff.emily + staff.tori}"
    assert not list(ast.vars_in(st.who.expr))
    # one definition may use another, in either order
    (st,) = parse(
        "b: {a + staff.z}\na: {staff.x + staff.y}\nREQUEST ALL_OF b DO 'x' DURING blocks.a"
    ).lines
    assert not list(ast.vars_in(st.who.expr))


def test_a_definition_with_a_quantifier_is_a_binding():
    (binding, _) = parse(
        "videographer: ANY 1 {staff.dylan + staff.donny}\n"
        "REQUEST ALL_OF {staff.charlton + videographer} DO 'x' DURING blocks.a"
    ).lines
    selector = binding.selector
    assert (selector.quantifier, selector.n, selector.var) == (ast.ANY_OF, 1, "videographer")
    (each, _) = parse("c: EACH_OF staff.counselor\nREQUEST c DO 'x' DURING blocks.a").lines
    assert isinstance(each, ast.Binding) and each.selector.quantifier == ast.EACH_OF


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("REQUEST ANY_1_OF staff.all DO 'x' DURING blocks.a", "write ANY 1, not ANY_1_OF"),
        ("REQUEST ANY 0 staff.all DO 'x' DURING blocks.a", "ANY needs a number of 1 or more"),
        ("a: staff.x\na: staff.y\nREQUEST a DO 'x' DURING blocks.a", "'a' is defined twice"),
        ("c: staff.x\nREQUEST EACH_OF c IN staff.all DO 'x' DURING blocks.a", "defined twice"),
        ("a: {b + staff.x}\nb: {a}\nREQUEST a DO 'x' DURING blocks.a", "in terms of itself"),
        (
            "IF ANY 1 staff.all FREE\nREQUEST staff.x FREE DURING blocks.a",
            "one assignment at a time",
        ),
        ("REQUEST staff.x NOT DO 'x' DURING ANY 2 blocks.all", "right of NOT a set"),
    ],
)
def test_new_errors(text, message):
    with pytest.raises(ast.SkedgeError) as info:
        parse(text)
    assert message in info.value.message
