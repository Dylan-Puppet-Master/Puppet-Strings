import re
from dataclasses import replace
from datetime import date

import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.namespaces import written
from puppet_strings.skedge.resolve import (
    ALL,
    ANY,
    POOL,
    Company,
    Forbid,
    Requirement,
    name_listing,
)
from puppet_strings.skedge.validate import validate_request
from tests.conftest import family_camp


def resolve(dataset, skedge, priority=Priority.HIGH):
    return validate_request(Request("t", "", skedge, priority), dataset)


def on(dataset, name, item=False):
    quantifier = "" if item else "ALL "
    (copy,) = resolve(
        dataset, f"REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON {quantifier}{name}"
    )
    return copy.statements[0].on.items


def test_defaults(dataset):
    (copy,) = resolve(dataset, "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    (st,) = copy.statements
    assert isinstance(st, Requirement) and copy.key == "" and not copy.conditions
    assert st.on.items == (dataset.target,) and st.on.kind == ALL
    assert st.who.items == ("dylan",) and st.who.kind == ALL
    assert st.during.items == ("clinic_1",) and st.role is None and st.minutes is None


def test_quantifiers(dataset):
    (copy,) = resolve(
        dataset,
        "REQUEST ANY 2 staff.counselor DO 'x' DURING ALL blocks ON ANY 1 dates.session_1",
    )
    (st,) = copy.statements
    assert (st.who.kind, st.who.n, st.who.items) == (ANY, 2, ("dylan", "james", "paul"))
    assert st.during.kind == ALL and set(st.during.items) == set(dataset.blocks)
    assert st.on.kind == ANY and st.on.items == dataset.session_dates


def test_each_of_expands_into_keyed_copies(dataset):
    copies = resolve(dataset, "REQUEST EACH staff.counselor DO 'x' DURING blocks.clinic_1")
    assert [c.key for c in copies] == ["dylan", "james", "paul"]
    assert copies[0].statements[0].who.items == ("dylan",)
    product = resolve(
        dataset,
        "REQUEST EACH staff.director DO 'x' DURING EACH {blocks.clinic_1 + blocks.clinic_2}",
    )
    assert [c.key for c in product] == [
        "david, clinic_1",
        "david, clinic_2",
        "lisa, clinic_1",
        "lisa, clinic_2",
    ]
    dated = resolve(
        dataset,
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON EACH dates.session_1.mondays",
    )
    assert [c.key for c in dated] == ["2026-09-14", "2026-09-21"]
    assert (
        resolve(
            dataset,
            "REQUEST EACH {staff.counselor & staff.director} DO 'x' DURING blocks.clinic_1",
        )
        == ()
    )


def test_a_binding_line_is_visible_on_every_line(dataset):
    copies = resolve(
        dataset,
        "EACH c IN staff.counselor\n"
        "m: REQUEST c DO 'a' DURING ANY 1 {blocks.clinic_1 + blocks.clinic_2}\n"
        "n: REQUEST c DO 'a' DURING ANY 1 {blocks.clinic_3 + blocks.clinic_4}\n"
        "GAP m TO n AT_MOST 5h",
    )
    assert [c.key for c in copies] == ["dylan", "james", "paul"]
    dylan = copies[0]
    assert all(s.who.items == ("dylan",) for s in dylan.statements)
    assert dylan.statements[0].during.kind == ANY and dylan.statements[0].label == "m"
    assert dylan.gaps[0].amount.value == 300


def test_an_on_on_the_first_line_is_every_statements(dataset):
    """An EACH there splits the request once, with every statement on the same date."""
    copies = resolve(
        dataset,
        "ON EACH dates.session_1.week_2\n"
        "REQUEST staff.dylan DO 'a' DURING blocks.clinic_1\n"
        "PREFER staff.rob FREE DURING AT_LEAST 1 blocks.clinic_2",
    )
    assert len(copies) == 7
    for copy in copies:
        requested, preferred = copy.statements
        assert len(requested.on.items) == 1 and requested.on.items == preferred.pattern.on.items
    with pytest.raises(SkedgeError, match="gives this its dates already"):
        resolve(
            dataset,
            "ON dates.target\nREQUEST staff.dylan DO 'a' DURING blocks.clinic_1 ON dates.target",
        )


def test_an_any_binding_is_one_choice_shared_by_the_declaration(dataset):
    (copy,) = resolve(
        dataset,
        "ANY 1 p IN staff.counselor\n"
        "first: REQUEST p DO 'setup' DURING blocks.clinic_4\n"
        "last:  REQUEST p DO 'teardown' DURING blocks.evening",
    )
    assert copy.bindings["p"].items == ("dylan", "james", "paul") and copy.bindings["p"].n == 1
    assert all(s.who.var == "p" and s.who.kind == ANY for s in copy.statements)


def test_negation_makes_a_pattern_of_pools(dataset):
    (copy,) = resolve(
        dataset,
        "REQUEST ALL staff.counselor NOT DO ANY activities.clinics.ropes WITHOUT staff.vic",
    )
    (st,) = copy.statements
    assert isinstance(st, Forbid) and st.who.kind == ALL
    assert st.pattern.who.kind == POOL and st.pattern.who.items == st.who.items
    assert st.pattern.what.kind == POOL and st.pattern.during is None
    assert st.pattern.on.items == (dataset.target,) and st.pattern.without == Company(
        frozenset({"vic"}), None
    )
    copies = resolve(dataset, "REQUEST EACH staff.counselor BUSY DURING blocks.clinic_1")
    assert copies[0].statements[0].what is None and copies[0].statements[0].busy


def test_with_takes_one_name_or_a_quantified_set(dataset):
    base = "REQUEST staff.rob NOT DO ANY activities.clinics.ropes "
    (copy,) = resolve(dataset, base + "WITH AT_LEAST 2 {staff.vic + staff.dylan + staff.randy}")
    assert copy.statements[0].pattern.with_ == Company(frozenset({"vic", "dylan", "randy"}), 2)
    (copy,) = resolve(dataset, base + "WITHOUT ALL {staff.vic + staff.dylan}")
    assert copy.statements[0].pattern.without == Company(frozenset({"vic", "dylan"}), None)
    with pytest.raises(SkedgeError, match="needs a quantifier: ALL or a count"):
        resolve(dataset, base + "WITHOUT {staff.vic + staff.dylan}")
    with pytest.raises(SkedgeError, match="is one item and takes no quantifier"):
        resolve(dataset, base + "WITH AT_LEAST 1 staff.vic")


def test_patterns_conditions_and_mappings(dataset):
    (copy,) = resolve(
        dataset,
        "EACH s IN staff.director\n"
        "IF s DO ANY activities.clinics DURING AT_LEAST 3 CONSECUTIVE blocks THEN\n"
        "{ REQUEST s FREE DURING ANY 1 blocks }",
    )[:1]
    ((condition,),) = copy.when
    (level,) = condition.test.tally.levels
    assert level.field == "block" and level.choice.n == 3 and level.choice.consecutive
    assert condition.test.tally.pattern.who.items == ("david",)
    copies = resolve(
        dataset,
        "PREFER EACH s IN staff.counselor DO EACH c IN activities.clinics.weapons "
        "MAXIMIZE mappings.preference(s, c)",
    )
    assert copies[0].statements[0].key == ("dylan", "archery_1_2")
    assert copies[0].statements[0].mapping == "preference" and copies[0].statements[0].maximize


def test_set_operators(dataset):
    text = "REQUEST EACH {staff - staff.director - staff.counselor} DO 'x' DURING ALL blocks"
    keys = {c.key for c in resolve(dataset, text)}
    assert keys and not keys & {"david", "lisa", "dylan", "james", "paul"}
    (copy,) = resolve(
        dataset,
        "REQUEST ALL {staff.counselor & staff.ropes_level_2} DO 'x' DURING ALL blocks",
    )
    assert copy.statements[0].who.items == ()


def test_date_windows(dataset):
    assert on(dataset, "{dates.target - 6d .. dates.target}") == dataset.session_dates[:4]
    assert on(dataset, "{dates.target + 1d .. dates.target + 10d}") == dataset.session_dates[4:]
    assert on(dataset, "{2026-10-20 .. 2026-10-21}") == ()  # no such camp days
    assert on(dataset, "dates.session_1.fridays") == (date(2026, 9, 18), date(2026, 9, 25))


def test_date_scopes(dataset):
    assert on(dataset, "dates.session_1") == dataset.session_dates
    assert on(dataset, "dates.session_1") == dataset.session_dates
    assert on(dataset, "dates.session_2") == dataset.span_dates(dataset.sessions[2])
    assert len(on(dataset, "dates.season")) == 21
    assert on(dataset, "dates.session_1.first", item=True) == (date(2026, 9, 13),)
    assert on(dataset, "dates.season.last", item=True) == (date(2026, 10, 3),)
    assert on(dataset, "dates.session_1.week_1.thursday", item=True) == (date(2026, 9, 17),)
    assert on(dataset, "dates.session_1.week_2.thursday", item=True) == (date(2026, 9, 24),)
    assert on(dataset, "dates.session_1.thursdays") == (date(2026, 9, 17), date(2026, 9, 24))
    # the nth-weekday names are gone: a week's weekday says it, and says it once
    with pytest.raises(SkedgeError, match="unknown name 'dates.session_1.second_thursday'"):
        on(dataset, "dates.session_1.second_thursday", item=True)
    with pytest.raises(SkedgeError, match="unknown name 'dates.season.first_mondays'"):
        on(dataset, "dates.season.first_mondays")
    with pytest.raises(SkedgeError, match="needs a quantifier"):
        resolve(
            dataset,
            "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON dates.session_1.mondays",
        )


def test_weeks_of_a_session(dataset):
    """A session holds its weeks, and a week holds one of each weekday."""
    assert on(dataset, "dates.session_1.week_1") == dataset.session_dates[:7]
    assert on(dataset, "dates.session_1.week_2") == dataset.session_dates[7:]
    assert on(dataset, "dates.session_1.week_1") == dataset.week_dates
    assert on(dataset, "dates.session_1.week_2.monday", item=True) == (date(2026, 9, 21),)
    assert on(dataset, "dates.session_2.week_1.monday", item=True) == (date(2026, 9, 28),)
    assert on(dataset, "dates.session_1.week_1.first", item=True) == (date(2026, 9, 13),)
    assert on(dataset, "dates.session_1.week_1.last", item=True) == (date(2026, 9, 19),)
    with pytest.raises(SkedgeError, match="unknown name 'dates.session_2.week_2'"):
        on(dataset, "dates.session_2.week_2")
    with pytest.raises(SkedgeError, match="did you mean 'dates.session_1.week_1'"):
        on(dataset, "dates.session_1.week_1.al")


def test_the_target_session_and_week_follow_the_target(dataset):
    """On 2026-09-16 the target is in session one's first week."""
    assert on(dataset, "dates.session_target") == on(dataset, "dates.session_1")
    assert on(dataset, "dates.session_target.mondays") == on(dataset, "dates.session_1.mondays")
    assert on(dataset, "dates.session_target.week_2.monday", item=True) == (date(2026, 9, 21),)
    assert on(dataset, "dates.session_target.week_target") == dataset.session_dates[:7]
    assert on(dataset, "dates.session_target.week_target.friday", item=True) == (date(2026, 9, 18),)
    later = replace(dataset, target=date(2026, 9, 29))
    assert on(later, "dates.session_target") == on(later, "dates.session_2")
    assert on(later, "dates.session_target.week_target.monday", item=True) == (date(2026, 9, 28),)


def test_a_date_in_no_session_has_no_target_session(dataset):
    camp = family_camp(dataset)
    assert on(camp, "dates.family_camp") == tuple(date(2026, 10, d) for d in range(4, 8))
    with pytest.raises(ast.NoSession, match="2026-10-05 is in Family Camp, which is not a session"):
        on(camp, "dates.session_target.week_target")
    with pytest.raises(SkedgeError) as caught:  # any other name is wrong in the usual way
        on(camp, "dates.session_1.week_9")
    assert not isinstance(caught.value, ast.NoSession)


def test_roles(dataset):
    (copy,) = resolve(
        dataset,
        "REQUEST staff.dylan DO activities.clinics.candle_making AS_ROLE roles.trainee DURING ANY 1 blocks.all_clinics",
    )
    assert copy.statements[0].role.items == ("trainee",)
    (copy,) = resolve(
        dataset,
        "PREFER staff.rob DO ANY activities.clinics.ropes AS_ROLE EACH {roles.first + roles.second} DURING AT_MOST 3 blocks",
    )[:1]
    assert copy.key == "first" and copy.statements[0].pattern.role.kind == ALL


def test_a_span_on_its_own_is_every_date_of_it(dataset):
    (copy,) = resolve(
        dataset, "REQUEST staff.dylan FREE DURING blocks.clinic_1 ON ANY dates.session_1"
    )
    assert len(copy.statements[0].on.items) == 14
    with pytest.raises(SkedgeError, match="unknown name 'staff.all'"):
        resolve(dataset, "REQUEST ANY 1 staff.all DO 'x' DURING blocks.clinic_1")


def test_name_listing_matches_the_namespaces(dataset):
    listing = name_listing(dataset)
    assert list(listing) == ["staff", "activities", "blocks", "dates", "roles", "mappings"]
    assert ("", "category, 21 members") in listing["staff"]
    assert ("", "category, 20 members") in listing["activities"]
    assert ("clinics", "category, 16 members") in listing["activities"]
    assert ("cabin_acts", "category, 4 members") in listing["activities"]
    assert ("cabin_acts.m1", "cabin M1") in listing["activities"]
    assert ("session_1.week_2.thursday", "2026-09-24 (Thursday)") in listing["dates"]
    assert ("session_2.week_1.monday", "2026-09-28 (Monday)") in listing["dates"]
    assert ("season.mondays", "3 dates") in listing["dates"]
    assert ("trainee", "trainee") in listing["roles"]
    assert ("preference", "staff, activities.clinics -> 1 to 5") in listing["mappings"]
    assert ("buddy", "staff.counselor -> {staff - staff.counselor}") in listing["mappings"]


BUDDY = "EACH c IN staff.counselor\nREQUEST {who} FREE DURING blocks.evening"


def test_a_mapping_gives_its_row_or_else_its_default_as_written(dataset):
    copies = resolve(dataset, BUDDY.format(who="mappings.buddy(c)"))
    who = {copy.key: copy.statements[0].who for copy in copies}
    assert (who["dylan"].items, who["dylan"].kind) == (("alan",), ALL)
    assert (who["james"].items, who["james"].kind) == (("sarah",), ALL)
    # Paul has no row, so his is the default: ANY 1 everyone but counselors and directors
    assert who["paul"].kind == ANY and who["paul"].n == 1
    everyone = set(dataset.staff_categories["all"])
    assert set(who["paul"].items) == everyone - {"dylan", "james", "paul", "david", "lisa"}


def test_a_mapping_is_a_set_among_sets(dataset):
    text = "REQUEST ALL {staff.office - mappings.buddy(staff.dylan)} FREE DURING blocks.evening"
    (copy,) = resolve(dataset, text)
    office = dataset.staff_categories["office"]
    assert set(copy.statements[0].who.items) == office - {"alan"}


@pytest.mark.parametrize(
    ("skedge", "message"),
    [
        (
            BUDDY.format(who="ALL {staff - mappings.buddy(c)}"),
            "its default is a choice the solver makes",
        ),
        (
            "REQUEST mappings.buddy(staff.alan) FREE DURING blocks.evening",
            "mappings.buddy takes staff.counselor here, and 'alan' is not in it",
        ),
        (
            "REQUEST mappings.buddy(blocks.evening) FREE DURING blocks.evening",
            "mappings.buddy takes a name from staff here, not blocks",
        ),
        (
            "REQUEST mappings.buddy(staff.dylan, staff.james) FREE DURING blocks.evening",
            "wrong number of arguments: mappings.buddy takes (staff.counselor), not 2",
        ),
        (
            "REQUEST staff.dylan DO mappings.buddy(staff.james) DURING blocks.evening",
            "expected a name from activities, but mappings.buddy gives one from staff",
        ),
        (
            "PREFER ANY staff DO ANY activities.clinics MAXIMIZE mappings.buddy(staff.dylan)",
            "not a number, so there is nothing to maximize or minimize",
        ),
        (
            "REQUEST mappings.preference(staff.dylan, activities.clinics.riflery) FREE "
            "DURING blocks.evening",
            "mappings.preference gives a number, not a name",
        ),
    ],
)
def test_a_mapping_is_checked_against_its_keys_and_value(dataset, skedge, message):
    with pytest.raises(SkedgeError, match=re.escape(message)):
        resolve(dataset, skedge)


def test_a_mapping_with_no_row_and_no_default_says_so(dataset):
    buddy = replace(dataset.mappings["buddy"], default=None)
    bare = replace(dataset, mappings={**dataset.mappings, "buddy": buddy})
    with pytest.raises(SkedgeError, match="mappings.buddy has no row for paul, and no default"):
        resolve(bare, BUDDY.format(who="mappings.buddy(c)"))


def test_ast_positions_survive_into_errors(dataset):
    with pytest.raises(SkedgeError) as info:
        resolve(dataset, "REQUEST staff.dylan DO activities.clinics.nope DURING blocks.clinic_1")
    assert (info.value.line, info.value.column) == (1, 24)
    assert isinstance(ast.Pos(1, 24), ast.Pos)


def test_each_of_the_cabin_acts_is_only_the_ones_on_the_day(dataset):
    copies = resolve(dataset, "REQUEST EACH activities.cabin_acts DURING blocks.cabin_act")
    days = [dataset.activities[c.statements[0].what.items[0]].day for c in copies]
    assert days == [dataset.target]
    week = resolve(
        dataset,
        "REQUEST EACH activities.cabin_acts DURING blocks.cabin_act "
        "ON EACH {2026-09-14 .. 2026-09-18}",
    )
    assert len(week) == 3  # Monday's, Wednesday's and Friday's; the 28th is another week


def test_the_board_splits_into_cabin_act_and_rest_hour_acts(dataset):
    """An act titled "RH: …" is under at_rest_hour; every other one is under at_cabin_act."""
    split = {
        name: resolve(
            dataset,
            f"REQUEST EACH {written('activities.cabin_acts', name)} DURING "
            "blocks.cabin_act ON EACH dates.season",
        )
        for name in ("", "at_cabin_act", "at_rest_hour")
    }
    acts = {n: {c.statements[0].what.items[0] for c in copies} for n, copies in split.items()}
    assert {dataset.activities[i].name for i in acts["at_rest_hour"]} == {"M1 RH: Gaga Ball"}
    assert acts["at_cabin_act"] | acts["at_rest_hour"] == acts[""]
    assert not acts["at_cabin_act"] & acts["at_rest_hour"]


def test_a_bound_cabin_act_on_another_day_is_no_copy(dataset):
    bound = resolve(dataset, "EACH a IN activities.cabin_acts\nREQUEST a DURING blocks.cabin_act")
    assert [c.statements[0].what.items for c in bound] == [("cabin_act_m2_2026_09_16",)]
    conditioned = resolve(
        dataset,
        "EACH a IN activities.cabin_acts\n"
        "IF staff.dylan DO a DURING blocks.cabin_act THEN\n"
        "{ REQUEST staff.dylan FREE DURING blocks.lunch }",
    )
    assert len(conditioned) == 1
