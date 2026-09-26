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
        "REQUEST ALL {staff.lucy + staff.tom} DO 'take out garbage' "
        "DURING AT_LEAST 1 blocks ON EACH dates.mondays"
    ).lines
    assert isinstance(st, ast.Requirement) and not st.negated and st.label is None
    assert st.who.quantifier == ast.ALL and st.who.pos == ast.Pos(1, 9)
    assert isinstance(st.who.expr, ast.SetOp) and st.who.expr.op == "+"
    assert st.who.expr.left == ast.Ref("staff", "lucy", ast.Pos(1, 14))
    assert st.what == ast.Task("take out garbage")
    during = ast.clause(st.clauses, ast.During).selector
    assert (during.quantifier, during.bound, during.n) == (ast.COUNT, ast.AT_LEAST, 1)
    assert during.expr == ast.Ref("blocks", "", ast.Pos(1, 78))
    on = ast.clause(st.clauses, ast.On).selector
    assert on.quantifier == ast.EACH and on.var is None
    assert on.expr == ast.Ref("dates", "mondays", ast.Pos(1, 93))


def test_negation_and_free():
    (forbid,) = parse(
        "REQUEST AT_LEAST 1 {staff.lucy + staff.tom} NOT DO 'break' WITHOUT staff.rob"
    ).lines
    assert forbid.negated and forbid.what == ast.Task("break")
    assert ast.clause(forbid.clauses, ast.Without).selector.expr == ast.Ref(
        "staff", "rob", ast.Pos(1, 68)
    )
    (free,) = parse("REQUEST staff.dylan FREE DURING ALL blocks ON 2026-09-16").lines
    assert free.what is None and not free.negated
    assert ast.clause(free.clauses, ast.On).selector.expr == ast.DateLiteral(
        date(2026, 9, 16), ast.Pos(1, 47)
    )
    (busy,) = parse("REQUEST EACH staff.counselor BUSY DURING blocks.clinic_1").lines
    assert busy.what is None and busy.busy and not busy.negated
    assert busy.who.quantifier == ast.EACH


def test_counts_and_lengths():
    (count,) = parse("REQUEST AT_MOST 2 staff DO 'break' DURING EACH blocks").lines
    assert isinstance(count, ast.Requirement)
    assert (count.who.quantifier, count.who.bound, count.who.n) == (ast.COUNT, ast.AT_MOST, 2)
    assert count.what == ast.Task("break")
    (hours,) = parse(
        "PREFER staff.cam_vl DO activities.clinics.candle_making AS_ROLE roles.trainee "
        "ACROSS {2026-09-14 .. 2026-09-18} ACROSS CONSECUTIVE blocks FOR AT_LEAST 2h"
    ).lines
    assert isinstance(hours, ast.Preference)
    assert ast.clause(hours.pattern.clauses, ast.During).consecutive
    assert ast.clause(hours.pattern.clauses, ast.During).across
    assert ast.clause(hours.pattern.clauses, ast.On).across
    assert ast.clause(hours.pattern.clauses, ast.For) == ast.For(ast.Pos(1, 139), 120, ast.AT_LEAST)
    role = ast.clause(hours.pattern.clauses, ast.AsRole).selector.expr
    assert role == ast.Ref("roles", "trainee", ast.Pos(1, 65))
    assert isinstance(ast.clause(hours.pattern.clauses, ast.On).selector.expr, ast.DateRange)


def test_mapping_statement():
    (score,) = parse(
        "PREFER EACH s IN staff DO EACH c IN activities.clinics "
        "MINIMIZE mappings.preference(s, activities.clinics.riflery)"
    ).lines
    assert isinstance(score, ast.Score) and not score.maximize
    assert score.mapping == ast.Ref("mappings", "preference", ast.Pos(1, 65))
    assert score.args == (
        ast.Var("s", ast.Pos(1, 85)),
        ast.Ref("activities", "clinics.riflery", ast.Pos(1, 88)),
    )
    assert (score.pattern.who.quantifier, score.pattern.who.var) == (ast.EACH, "s")
    assert score.pattern.what.var == "c"


def test_a_mapping_call_is_a_set():
    (binding, request) = parse(
        "EACH c IN staff.counselor\n"
        "REQUEST ALL {staff.office - mappings.buddy(c)} FREE DURING blocks.evening"
    ).lines
    call = request.who.expr.right
    assert call == ast.Call(
        ast.Ref("mappings", "buddy", ast.Pos(2, 29)),
        (ast.Var("c", ast.Pos(2, 44)),),
        ast.Pos(2, 29),
    )


def test_mapping_cells_parse_on_their_own():
    for text in ("{staff - staff.counselor}", "staff - staff.counselor"):
        assert isinstance(parse_domain(text), ast.SetOp)  # the braces are optional
    default = parse_default("AT_LEAST 1 {staff - staff.counselor}")
    assert (default.quantifier, default.bound, default.n) == (ast.COUNT, ast.AT_LEAST, 1)


def test_bindings_conditions_labels_and_gaps():
    lines = parse(
        "ANY 2 p IN staff.counselor\n"
        "UNLESS p DO ANY activities.clinics DURING AT_LEAST 3 CONSECUTIVE blocks {\n"
        "first: REQUEST p DO 'campfire setup' DURING blocks.clinic_4\n"
        "last:  REQUEST p DO 'campfire teardown' DURING blocks.evening\n"
        "}\n"
        "GAP first TO last AT_LEAST 0m\n"
        "IF staff.rob FREE { REQUEST staff.rob DO 'x' DURING blocks.lunch }"
    ).lines
    binding, unless, first, last, gap, if_, lunch = lines
    assert isinstance(binding, ast.Binding)
    selector = binding.selector
    assert (selector.quantifier, selector.n, selector.var) == (ast.ANY_OF, 2, "p")
    during = ast.clause(unless.test.pattern.clauses, ast.During)
    assert unless.unless and during.consecutive and during.selector.n == 3
    assert unless.test.pattern.who.expr == ast.Var("p", ast.Pos(2, 8))
    assert (first.label, last.label) == ("first", "last") and first.pos == ast.Pos(3, 8)
    assert first.when == last.when == (unless.pos,)
    assert gap == ast.Gap(
        "first", "last", ast.Amount(ast.AT_LEAST, 0, True, ast.Pos(6, 19)), ast.Pos(6, 1)
    )
    assert not if_.unless and if_.test.pattern.what is None
    assert lunch.when == (if_.pos,)


def test_a_block_may_hold_another_and_sit_beside_what_always_applies():
    outer, rob, inner, vic, prefer, always = parse(
        "IF staff.rob FREE DURING blocks.lunch\n"
        "{\n"
        "    REQUEST staff.rob DO 'x' DURING blocks.lunch\n"
        "    IF staff.vic FREE DURING blocks.lunch { REQUEST staff.vic DO 'x' DURING blocks.lunch }\n"
        "    PREFER staff.rob FREE DURING AT_LEAST 1 blocks.dinner\n"
        "}\n"
        "REQUEST staff.rob FREE DURING blocks.dinner"
    ).lines
    assert isinstance(outer, ast.Condition) and isinstance(inner, ast.Condition)
    assert rob.when == prefer.when == (outer.pos,)
    assert vic.when == (outer.pos, inner.pos) == (ast.Pos(1, 1), ast.Pos(4, 5))
    assert always.when == ()


def test_conditions_join_with_and_and_or_over_several_lines():
    (if_, _) = parse(
        "IF\n"
        "ANY staff.counselor DO 'break' DURING AT_LEAST 2 CONSECUTIVE blocks\n"
        "AND\n"
        "staff.dylan FREE DURING blocks.lunch\n"
        "{\n"
        "    REQUEST staff.rob DO 'x' DURING blocks.lunch\n"
        "}"
    ).lines
    assert isinstance(if_.test, ast.Junction) and if_.test.all
    first, second = if_.test.parts
    assert ast.clause(first.pattern.clauses, ast.During).selector.n == 2
    assert second.pattern.what is None
    (unless, _) = parse(
        "UNLESS (ANY staff.a FREE and ANY staff.b FREE)\n"
        "OR staff.c FREE\n"
        "{ REQUEST staff.rob DO 'x' DURING blocks.lunch }"
    ).lines
    assert unless.unless and not unless.test.all
    assert [type(p) for p in unless.test.parts] == [ast.Junction, ast.Predicate]
    assert len(list(ast.predicates(unless.test))) == 3


def test_mixing_and_with_or_needs_parentheses():
    with pytest.raises(ast.SkedgeError, match="mixed AND and OR need parentheses"):
        parse(
            "IF ANY staff.a FREE AND ANY staff.b FREE OR ANY staff.c FREE { REQUEST staff.rob FREE }"
        )


def test_a_namespace_on_its_own_is_every_name_in_it():
    (line,) = parse("REQUEST ANY 1 staff DO 'x' DURING ANY blocks").lines
    assert line.who.expr == ast.Ref("staff", "", ast.Pos(1, 15))
    assert ast.spoken(line.who.expr) == "staff"


@pytest.mark.parametrize(
    "text",
    [
        "EACH staff IN staff.counselor\nREQUEST staff FREE DURING blocks.clinic_1",
        "blocks: blocks.meals\nREQUEST staff.dylan FREE DURING ALL blocks",
        "dates: REQUEST staff.dylan DO 'x' DURING blocks.clinic_1",
    ],
)
def test_nothing_else_can_be_named_after_a_namespace(text):
    with pytest.raises(ast.SkedgeError, match="is a namespace"):
        parse(text)


def test_set_expressions():
    (st,) = parse(
        "REQUEST staff.dylan DO 'x' DURING blocks.a ON ANY 1 {dates.target - 6d .. dates.target}"
    ).lines
    on = ast.clause(st.clauses, ast.On).selector.expr
    assert isinstance(on, ast.DateRange)
    assert on.start == ast.DateOffset(
        ast.Ref("dates", "target", ast.Pos(1, 54)), -6, ast.Pos(1, 54)
    )
    assert on.end.name == "target"
    (st,) = parse(
        "REQUEST EACH {staff - staff.director - staff.counselor} DO 'x' DURING blocks.a"
    ).lines
    expr = st.who.expr
    assert expr.op == "-" and expr.right.name == "counselor"
    assert expr.left.op == "-" and expr.left.left.name == ""
    (st,) = parse(
        "REQUEST EACH {staff - {staff.counselor & staff.director}} DO 'x' DURING blocks.a"
    ).lines
    assert st.who.expr.right.op == "&"
    (st,) = parse(
        "REQUEST staff.x DO 'x' ON EACH {{2026-07-21 .. 2026-08-08} & dates.tuesdays}"
    ).lines
    on = ast.clause(st.clauses, ast.On).selector.expr
    assert on.op == "&" and isinstance(on.left, ast.DateRange)


@pytest.mark.parametrize(
    "text",
    [
        "IF staff.dylan FREE DURING blocks.lunch\nREQUEST staff.rob FREE",
        "UNLESS staff.dylan FREE DURING blocks.lunch\nREQUEST staff.rob FREE",
        "REQUEST ALL {staff - (staff.a & staff.b)} FREE",
        "REQUEST staff.x DO 'x' ON EACH {dates.season & (2026-07-21 .. dates.target)}",
        "REQUEST staff.x DO 'x' ON EACH {dates.season & 2026-07-21 .. dates.target}",
        "REQUEST staff.dylan DO 'x' DURING AT_LEAST 2 blocks CONSECUTIVE",
        "REQUEST AT_MOST 2 ANY staff DO 'break'",
        "REQUEST AT_MOST 2 EACH staff DO 'break'",
        "REQUEST AT_LEAST 2h staff.cam DO 'x'",
        "REQUEST staff.cam DO AT_LEAST 2h 'x'",
        "REQUEST staff.cam DO AT_MOST 2 'x'",
        "REQUEST staff.cam NOT FREE DURING blocks.a",
        "REQUEST staff.cam NOT BUSY DURING blocks.a",
        "IF staff.cam NOT FREE DURING blocks.a { REQUEST staff.x FREE }",
        "REQUEST staff.rob DO 'x' FOR 30m DURING blocks.a",
        "REQUEST ANY_1_OF staff DO 'x' DURING blocks.a",
        "AT_LEAST 1 x IN staff\nREQUEST x FREE",
        "EXACTLY 1 x IN staff\nREQUEST x FREE",
        "REQUEST ALL {staff.x + (AT_LEAST 1 staff)} FREE",
        "REQUEST ALL {staff.a + AT_MOST 1 {staff.b + staff.c}} FREE",
        "REQUEST ALL_OF staff.counselor DO 'x' DURING blocks.clinic_1",
        "REQUEST staff.dylan DO 'x' ON EACH_OF dates.season",
        "a: REQUEST staff.dylan DO 'x' DURING blocks.a\nb: REQUEST staff.dylan DO 'y' DURING "
        "blocks.b\nGAP a TO b AT_LEAST 3",
    ],
)
def test_what_skedge_no_longer_says_is_refused(text):
    with pytest.raises(ast.SkedgeError):
        parse(text)
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
        "first:  REQUEST staff.rob DO 'setup' FOR EXACTLY 1h DURING blocks.clinic_1\n"
        "second: REQUEST staff.rob DO 'strike' FOR EXACTLY 1h DURING blocks.clinic_2\n"
        "GAP first TO second AT_LEAST {amount}"
    )
    (days,) = parse(text.format(amount="2d")).gaps
    (hours,) = parse(text.format(amount="48h")).gaps
    assert days.amount == hours.amount
    assert days.amount.value == 2880 and days.amount.duration


def test_exclude_statement():
    (line,) = parse("EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks ON 2026-08-26").lines
    assert isinstance(line, ast.Exclude)
    assert line.who.expr == ast.Ref("staff", "dylan", ast.Pos(1, 9))
    assert line.label == "offsite"  # a label for the schedule, not an activity
    assert ast.clause(line.clauses, ast.During).selector.quantifier == ast.ALL
    assert ast.clause(line.clauses, ast.On).selector.expr.value == date(2026, 8, 26)
    (bare,) = parse("EXCLUDE staff.dylan DO 'offsite'").lines  # every block of the day
    assert bare.clauses == ()


def test_a_keyword_may_be_written_in_either_case():
    """Upper case is the convention; lower case is the same request, not an error."""
    shouted = parse("REQUEST ALL staff.counselor DO 'x' FOR EXACTLY 30m DURING AT_LEAST 1 blocks")
    quiet = parse("request all staff.counselor do 'x' for exactly 30m during at_least 1 blocks")
    assert shouted == quiet
    (binding, line) = parse(
        "each c in staff.counselor\nrequest c busy during blocks.clinic_1"
    ).lines
    assert binding.selector.quantifier == ast.EACH and line.busy
    (count,) = parse("prefer any staff do 'break' during at_most 2 consecutive blocks").lines
    during = ast.clause(count.pattern.clauses, ast.During)
    assert during.selector.bound == ast.AT_MOST and during.consecutive


def test_consecutive_goes_on_the_blocks():
    """A count of blocks in a row, or a pool of them added up a run at a time."""
    (measured,) = parse(
        "REQUEST staff.dylan DO 'x' ACROSS CONSECUTIVE blocks FOR AT_LEAST 2h"
    ).lines
    assert ast.clause(measured.clauses, ast.During).consecutive
    (run,) = parse("REQUEST staff.dylan DO 'x' DURING ANY 2 CONSECUTIVE blocks").lines
    during = ast.clause(run.clauses, ast.During)
    assert during.consecutive and during.selector.n == 2 and not during.selector.consecutive
    (plain,) = parse("REQUEST staff.dylan DO 'x' DURING ANY 2 blocks").lines
    assert not ast.clause(plain.clauses, ast.During).consecutive


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("REQUEST AT_LEAST 2 CONSECUTIVE staff.dylan DO 'x'", "CONSECUTIVE is about blocks"),
        (
            "REQUEST staff.dylan DO 'x' DURING ALL CONSECUTIVE blocks",
            "after ANY, ANY n or a count",
        ),
        ("REQUEST staff.dylan DO 'x' ON AT_LEAST 2 CONSECUTIVE dates.season", "about blocks"),
        (
            "IF staff.dylan DO ANY activities.clinics DURING ANY CONSECUTIVE blocks\n"
            "{ REQUEST staff.dylan FREE }",
            "a run of blocks to add a FOR up over",
        ),
        ("REQUEST staff.dylan DO 'x' ACROSS blocks", "with no FOR, write DURING"),
        ("REQUEST staff.dylan DO 'x' FOR AT_LEAST 1h ACROSS ANY blocks", "takes no ANY"),
        ("REQUEST staff.dylan DO 'x' ACROSS staff.rob", "names one or the other"),
        ("REQUEST staff.dylan DO 'x' ACROSS ANY 2 dates.season", "ACROSS takes its dates whole"),
        (
            "REQUEST staff.dylan DO 'x' ACROSS AT_MOST 2 dates.season",
            "ACROSS takes its dates whole",
        ),
        (
            "REQUEST staff.dylan DO 'x' ACROSS CONSECUTIVE dates.season",
            "CONSECUTIVE is about blocks",
        ),
        ("ACROSS blocks\nREQUEST staff.dylan DO 'x'", "over the dates of every statement"),
        (
            "REQUEST staff.dylan NOT DO 'x' ACROSS dates.season",
            "right of NOT nothing is added up",
        ),
        (
            "REQUEST staff.dylan NOT DO 'x' FOR AT_LEAST 1h ACROSS blocks",
            "right of NOT each piece is matched on its own",
        ),
        (
            "PREFER staff.dylan DO 'x' FOR AT_LEAST 1h ACROSS blocks "
            "MAXIMIZE mappings.m(staff.dylan)",
            "a score adds nothing up",
        ),
        ("REQUEST staff.cam FOR EXACTLY 30m DO 'x' DURING blocks.a", "FOR describes the activity"),
        ("REQUEST WITH staff.x staff.cam FREE DURING blocks.a", "so it goes after FREE"),
    ],
)
def test_misplaced_words_say_where_they_go(text, message):
    with pytest.raises(ast.SkedgeError) as e:
        parse(text)
    assert message in e.value.message


def test_consecutive_right_of_not_says_to_count_the_run():
    """Right of NOT nothing is chosen, so the message points at the count that limits runs."""
    with pytest.raises(ast.SkedgeError) as e:
        parse("REQUEST EACH staff NOT DO 'break' DURING ANY CONSECUTIVE blocks")
    assert e.value.message.startswith("right of NOT there are no blocks to choose")
    assert "DURING AT_MOST 1 CONSECUTIVE" in e.value.message


def test_a_name_that_starts_with_a_keyword_is_still_a_name():
    """`FOR` ends at a word boundary, so `format` is one word and not two."""
    (binding, _) = parse(
        "each format in staff.counselor\nrequest format do 'x' during blocks.a"
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
        (
            "REQUEST staff.rob DO 'x' FOR EXACTLY 1.25m DURING blocks.a",
            "whole number of minutes",
            1,
            38,
        ),
        ("REQUEST staff.rob NOT DO AT_LEAST 1 activities.clinics", "right of NOT a set", 1, 26),
        ("morning: PREFER staff DO 'x' DURING AT_MOST 1 blocks", "expected one of", 1, 10),
        ("REQUEST AT_MOST 1 staff CONSECUTIVE", "expected one of", 1, 25),
        ("PREFER staff DO 'x' MAXIMIZE", "expected one of", 1, 29),
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
        "ALL {x + staff.alesa}\n"
        "DO 'video'\n"
        "FOR EXACTLY 30m\n"
        "DURING ANY 1 blocks"
    ).lines[0]
    assert [type(c) for c in written.clauses] == [ast.On, ast.For, ast.During]
    assert written.who.quantifier == ast.ALL and written.what == ast.Task("video")
    between = parse("REQUEST staff.rob DURING blocks.a DO 'x' ON dates.target").lines[0]
    assert [type(c) for c in between.clauses] == [ast.During, ast.On]
    (count,) = parse("REQUEST DURING blocks.lunch AT_MOST 2 staff DO 'break'").lines
    assert ast.clause(count.clauses, ast.During) is not None
    (after,) = parse("REQUEST staff.rob DO AS_ROLE roles.first activities.clinics.x").lines
    assert ast.clause(after.clauses, ast.AsRole) is not None  # after DO, before the object
    (score,) = parse(
        "PREFER ANY staff DO ANY activities.clinics MAXIMIZE mappings.pref(s) DURING ANY blocks.a"
    ).lines
    assert ast.clause(score.pattern.clauses, ast.During) is not None


def test_a_line_that_cannot_start_a_statement_continues_the_one_above():
    lines = parse(
        "EACH c IN staff.counselor\n"
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
        "REQUEST ALL {staff.charlton + (ANY 1 {staff.dylan + staff.donny})} DO 'x' DURING blocks.a"
    ).lines
    group = st.who.expr.right
    assert isinstance(group, ast.Group) and (group.quantifier, group.n) == (ast.ANY_OF, 1)
    (st,) = parse(
        "REQUEST ANY 1 {staff.x + (ALL {staff.y + staff.z})} DO 'x' DURING blocks.a"
    ).lines
    assert st.who.expr.right.quantifier == ast.ALL


def test_a_definition_is_written_in_where_it_is_used():
    (st,) = parse(
        "office_elves: {staff.emily + staff.tori}\n"
        "REQUEST EACH {staff.directors + office_elves} DO 'DYOW' DURING blocks.a"
    ).lines
    assert ast.spoken(st.who.expr.right) == "{staff.emily + staff.tori}"
    assert not list(ast.vars_in(st.who.expr))
    # one definition may use another, in either order
    (st,) = parse(
        "b: {a + staff.z}\na: {staff.x + staff.y}\nREQUEST ALL b DO 'x' DURING blocks.a"
    ).lines
    assert not list(ast.vars_in(st.who.expr))


def test_a_definition_with_a_quantifier_is_a_binding():
    (binding, _) = parse(
        "videographer: ANY 1 {staff.dylan + staff.donny}\n"
        "REQUEST ALL {staff.charlton + videographer} DO 'x' DURING blocks.a"
    ).lines
    selector = binding.selector
    assert (selector.quantifier, selector.n, selector.var) == (ast.ANY_OF, 1, "videographer")
    (each, _) = parse("c: EACH staff.counselor\nREQUEST c DO 'x' DURING blocks.a").lines
    assert isinstance(each, ast.Binding) and each.selector.quantifier == ast.EACH


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("REQUEST AT_LEAST 0 staff DO 'x' DURING blocks.a", "amount must be at least 1"),
        ("REQUEST EXACTLY 0 staff DO 'x' DURING blocks.a", "write NOT DO"),
        ("REQUEST ANY 0 staff DO 'x' DURING blocks.a", "ANY needs a number of 1 or more"),
        ("a: staff.x\na: staff.y\nREQUEST a DO 'x' DURING blocks.a", "'a' is defined twice"),
        ("c: staff.x\nREQUEST EACH c IN staff DO 'x' DURING blocks.a", "defined twice"),
        ("a: {b + staff.x}\nb: {a}\nREQUEST a DO 'x' DURING blocks.a", "in terms of itself"),
        (
            "PREFER AT_LEAST 1 staff FREE MAXIMIZE mappings.x(staff.y)",
            "one assignment at a time",
        ),
        ("REQUEST staff.x NOT DO 'x' DURING AT_LEAST 2 blocks", "right of NOT a set"),
    ],
)
def test_new_errors(text, message):
    with pytest.raises(ast.SkedgeError) as info:
        parse(text)
    assert message in info.value.message


def test_a_role_straight_after_with_is_the_companys():
    (st,) = parse(
        "REQUEST staff.caroline DO activities.clinics.climbing_wall AS_ROLE roles.trainee "
        "WITH staff.alan AS_ROLE roles.first"
    ).lines
    assert ast.clause(st.clauses, ast.AsRole).selector.expr.name == "trainee"
    with_ = ast.clause(st.clauses, ast.With)
    assert with_.selector.expr.name == "alan" and with_.role.expr.name == "first"
    (before,) = parse(
        "REQUEST staff.caroline DO activities.clinics.climbing_wall WITH staff.alan "
        "DURING blocks.a AS_ROLE roles.trainee"
    ).lines
    assert ast.clause(before.clauses, ast.With).role is None  # not straight after: the subject's


def test_a_gap_with_no_amount_is_only_the_order():
    text = (
        "a: REQUEST staff.rob DO 'x' DURING blocks.a\nb: REQUEST staff.rob DO 'y' DURING blocks.b\n"
    )
    (bare,) = parse(text + "GAP a TO b").gaps
    (zero,) = parse(text + "GAP a TO b AT_LEAST 0m").gaps
    assert (bare.amount.bound, bare.amount.value, bare.amount.duration) == (ast.AT_LEAST, 0, True)
    assert bare.amount.value == zero.amount.value


def test_a_task_may_be_named_and_used_after_do():
    lines = parse(
        "duty: 'on duty'\n"
        "REQUEST staff.rob DO duty DURING blocks.a\n"
        "IF staff.vic DO duty DURING blocks.b { REQUEST staff.vic NOT DO duty }"
    ).lines
    assert all(
        (x.what if isinstance(x, ast.Requirement) else x.test.pattern.what) == ast.Task("on duty")
        for x in lines
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "duty: 'on duty'\nREQUEST ALL {staff.rob + duty} FREE",
            "names a task, which goes after DO",
        ),
        ("duty: 'on duty'\nREQUEST staff.rob DO ANY duty", "names one task, so no quantifier"),
        ("duty: 'on duty'\nduty: staff.rob\nREQUEST duty FREE", "is defined twice"),
    ],
)
def test_a_task_name_stands_only_where_a_task_can(text, message):
    with pytest.raises(ast.SkedgeError, match=message):
        parse(text)


def test_a_group_needs_no_parentheses():
    bare = parse("REQUEST ALL {staff.a + ANY 1 {staff.b + staff.c}} FREE").lines[0]
    wrapped = parse("REQUEST ALL {staff.a + (ANY 1 {staff.b + staff.c})} FREE").lines[0]
    group = bare.who.expr.right
    assert isinstance(group, ast.Group) and (group.quantifier, group.n) == (ast.ANY_OF, 1)
    assert ast.spoken(group.expr) == ast.spoken(wrapped.who.expr.right.expr)


def test_a_block_follows_its_test_with_no_word_between():
    """A set that opens with a brace is the test's; the brace after the whole test is its block."""
    (condition, inside) = parse(
        "IF DURING blocks.a {activities.x + activities.y}\n{ REQUEST staff.rob FREE }"
    ).lines
    assert isinstance(condition, ast.Condition)
    assert isinstance(condition.test.pattern.what.expr, ast.SetOp)
    assert inside.when == (condition.pos,)
