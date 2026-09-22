import re
from dataclasses import replace
from datetime import date

import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import ALL, ANY, POOL, Forbid, Requirement, name_listing
from puppet_strings.skedge.validate import validate_request


def resolve(dataset, skedge, priority=Priority.HIGH):
    return validate_request(Request("t", "", skedge, priority), dataset)


def on(dataset, name, item=False):
    quantifier = "" if item else "ALL_OF "
    (copy,) = resolve(
        dataset, f"REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON {quantifier}{name}"
    )
    return copy.statements[0].on.items


def test_defaults(dataset):
    (copy,) = resolve(dataset, "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1")
    (st,) = copy.statements
    assert isinstance(st, Requirement) and copy.key == "" and copy.condition is None
    assert st.on.items == (dataset.target,) and st.on.kind == ALL
    assert st.who.items == ("dylan",) and st.who.kind == ALL
    assert st.during.items == ("clinic_1",) and st.role is None and st.minutes is None


def test_quantifiers(dataset):
    (copy,) = resolve(
        dataset,
        "REQUEST ANY_2_OF staff.counselor DO 'x' DURING ALL_OF blocks.all ON ANY_1_OF dates.session.one.all",
    )
    (st,) = copy.statements
    assert (st.who.kind, st.who.n, st.who.items) == (ANY, 2, ("dylan", "james", "paul"))
    assert st.during.kind == ALL and set(st.during.items) == set(dataset.blocks)
    assert st.on.kind == ANY and st.on.items == dataset.session_dates


def test_each_of_expands_into_keyed_copies(dataset):
    copies = resolve(dataset, "REQUEST EACH_OF staff.counselor DO 'x' DURING blocks.clinic_1")
    assert [c.key for c in copies] == ["dylan", "james", "paul"]
    assert copies[0].statements[0].who.items == ("dylan",)
    product = resolve(
        dataset,
        "REQUEST EACH_OF staff.director DO 'x' DURING EACH_OF {blocks.clinic_1 + blocks.clinic_2}",
    )
    assert [c.key for c in product] == [
        "david, clinic_1",
        "david, clinic_2",
        "lisa, clinic_1",
        "lisa, clinic_2",
    ]
    dated = resolve(
        dataset,
        "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON EACH_OF dates.session.one.mondays",
    )
    assert [c.key for c in dated] == ["2026-09-14", "2026-09-21"]
    assert (
        resolve(
            dataset,
            "REQUEST EACH_OF {staff.counselor & staff.director} DO 'x' DURING blocks.clinic_1",
        )
        == ()
    )


def test_a_binding_line_is_visible_on_every_line(dataset):
    copies = resolve(
        dataset,
        "EACH_OF c IN staff.counselor\n"
        "m: REQUEST c DO 'a' DURING ANY_1_OF {blocks.clinic_1 + blocks.clinic_2}\n"
        "n: REQUEST c DO 'a' DURING ANY_1_OF {blocks.clinic_3 + blocks.clinic_4}\n"
        "GAP m TO n AT_MOST 5h",
    )
    assert [c.key for c in copies] == ["dylan", "james", "paul"]
    dylan = copies[0]
    assert all(s.who.items == ("dylan",) for s in dylan.statements)
    assert dylan.statements[0].during.kind == ANY and dylan.statements[0].label == "m"
    assert dylan.gaps[0].amount.value == 300


def test_an_any_binding_is_one_choice_shared_by_the_declaration(dataset):
    (copy,) = resolve(
        dataset,
        "ANY_1_OF p IN staff.counselor\n"
        "first: REQUEST p DO 'setup' DURING blocks.clinic_4\n"
        "last:  REQUEST p DO 'teardown' DURING blocks.evening",
    )
    assert copy.bindings["p"].items == ("dylan", "james", "paul") and copy.bindings["p"].n == 1
    assert all(s.who.var == "p" and s.who.kind == ANY for s in copy.statements)


def test_negation_makes_a_pattern_of_pools(dataset):
    (copy,) = resolve(
        dataset, "REQUEST ALL_OF staff.counselor NOT DO activities.clinics.ropes WITHOUT staff.vic"
    )
    (st,) = copy.statements
    assert isinstance(st, Forbid) and st.who.kind == ALL
    assert st.pattern.who.kind == POOL and st.pattern.who.items == st.who.items
    assert st.pattern.what.kind == POOL and st.pattern.during is None
    assert st.pattern.on.items == (dataset.target,) and st.pattern.without == frozenset({"vic"})
    copies = resolve(dataset, "REQUEST EACH_OF staff.counselor NOT FREE DURING blocks.clinic_1")
    assert copies[0].statements[0].pattern.what is None and copies[0].statements[0].pattern.busy


def test_patterns_conditions_and_mappings(dataset):
    (copy,) = resolve(
        dataset,
        "EACH_OF s IN staff.director\n"
        "IF AT_LEAST 3 s DO activities.clinics.all CONSECUTIVE\n"
        "REQUEST s FREE DURING ANY_1_OF blocks.all",
    )[:1]
    assert copy.condition.test.amount.value == 3 and copy.condition.test.consecutive
    assert copy.condition.test.pattern.who.items == ("david",)
    copies = resolve(
        dataset,
        "PREFER EACH_OF s IN staff.counselor DO EACH_OF c IN activities.clinics.weapons "
        "MAXIMIZE mappings.preference(s, c)",
    )
    assert copies[0].statements[0].key == ("dylan", "archery_1_2")
    assert copies[0].statements[0].mapping == "preference" and copies[0].statements[0].maximize


def test_set_operators(dataset):
    text = "REQUEST EACH_OF {staff.all - staff.director - staff.counselor} DO 'x' DURING ALL_OF blocks.all"
    keys = {c.key for c in resolve(dataset, text)}
    assert keys and not keys & {"david", "lisa", "dylan", "james", "paul"}
    (copy,) = resolve(
        dataset,
        "REQUEST ALL_OF {staff.counselor & staff.ropes_level_2} DO 'x' DURING ALL_OF blocks.all",
    )
    assert copy.statements[0].who.items == ()


def test_date_windows(dataset):
    assert on(dataset, "{(dates.target - 6d) .. dates.target}") == dataset.session_dates[:4]
    assert on(dataset, "{(dates.target + 1d) .. (dates.target + 10d)}") == dataset.session_dates[4:]
    assert on(dataset, "{2026-10-20 .. 2026-10-21}") == ()  # no such camp days
    assert on(dataset, "dates.session.one.fridays") == (date(2026, 9, 18), date(2026, 9, 25))


def test_date_scopes(dataset):
    assert on(dataset, "dates.session.one.all") == dataset.session_dates
    assert on(dataset, "dates.session.one.all") == dataset.session_dates
    assert on(dataset, "dates.session.two.all") == dataset.span_dates(dataset.sessions[2])
    assert len(on(dataset, "dates.season.all")) == 21
    assert on(dataset, "dates.session.one.first", item=True) == (date(2026, 9, 13),)
    assert on(dataset, "dates.season.last", item=True) == (date(2026, 10, 3),)
    assert on(dataset, "dates.session.one.week.one.thursday", item=True) == (date(2026, 9, 17),)
    assert on(dataset, "dates.session.one.week.two.thursday", item=True) == (date(2026, 9, 24),)
    assert on(dataset, "dates.session.one.thursdays") == (date(2026, 9, 17), date(2026, 9, 24))
    # the nth-weekday names are gone: a week's weekday says it, and says it once
    with pytest.raises(SkedgeError, match="unknown name 'dates.session.one.second_thursday'"):
        on(dataset, "dates.session.one.second_thursday", item=True)
    with pytest.raises(SkedgeError, match="unknown name 'dates.season.first_mondays'"):
        on(dataset, "dates.season.first_mondays")
    with pytest.raises(SkedgeError, match="needs a quantifier"):
        resolve(
            dataset,
            "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1 ON dates.session.one.mondays",
        )


def test_weeks_of_a_session(dataset):
    """A session holds its weeks, and a week holds one of each weekday."""
    assert on(dataset, "dates.session.one.week.one.all") == dataset.session_dates[:7]
    assert on(dataset, "dates.session.one.week.two.all") == dataset.session_dates[7:]
    assert on(dataset, "dates.session.one.week.one.all") == dataset.week_dates
    assert on(dataset, "dates.session.one.week.two.monday", item=True) == (date(2026, 9, 21),)
    assert on(dataset, "dates.session.two.week.one.monday", item=True) == (date(2026, 9, 28),)
    assert on(dataset, "dates.session.one.week.one.first", item=True) == (date(2026, 9, 13),)
    assert on(dataset, "dates.session.one.week.one.last", item=True) == (date(2026, 9, 19),)
    with pytest.raises(SkedgeError, match="unknown name 'dates.session.two.week.two.all'"):
        on(dataset, "dates.session.two.week.two.all")
    with pytest.raises(SkedgeError, match="did you mean 'dates.session.one.week.one.all'"):
        on(dataset, "dates.session.one.week.one.al")


def test_roles(dataset):
    (copy,) = resolve(
        dataset,
        "REQUEST staff.dylan DO activities.clinics.candle_making AS_ROLE roles.trainee DURING ANY_1_OF blocks.any_clinic",
    )
    assert copy.statements[0].role.items == ("trainee",)
    (copy,) = resolve(
        dataset,
        "PREFER AT_MOST 3 staff.rob DO activities.clinics.ropes AS_ROLE EACH_OF {roles.first + roles.second}",
    )[:1]
    assert copy.key == "first" and copy.statements[0].pattern.role.kind == POOL


def test_name_listing_matches_the_namespaces(dataset):
    listing = name_listing(dataset)
    assert list(listing) == ["staff", "activities", "blocks", "dates", "roles", "mappings"]
    assert ("all", "category, 21 members") in listing["staff"]
    assert ("all", "category, 20 members") in listing["activities"]
    assert ("clinics.all", "category, 16 members") in listing["activities"]
    assert ("cabin_acts.all", "category, 4 members") in listing["activities"]
    assert ("cabin_acts.m1", "cabin M1") in listing["activities"]
    assert ("session.one.week.two.thursday", "2026-09-24 (Thursday)") in listing["dates"]
    assert ("session.two.week.one.monday", "2026-09-28 (Monday)") in listing["dates"]
    assert ("season.mondays", "3 dates") in listing["dates"]
    assert ("trainee", "trainee") in listing["roles"]
    assert ("preference", "staff, activities.clinics.all -> 1 to 5") in listing["mappings"]
    assert ("buddy", "staff.counselor -> {staff.all - staff.counselor}") in listing["mappings"]


BUDDY = "EACH_OF c IN staff.counselor\nREQUEST {who} FREE DURING blocks.evening"


def test_a_mapping_gives_its_row_or_else_its_default_as_written(dataset):
    copies = resolve(dataset, BUDDY.format(who="mappings.buddy(c)"))
    who = {copy.key: copy.statements[0].who for copy in copies}
    assert (who["dylan"].items, who["dylan"].kind) == (("alan",), ALL)
    assert (who["james"].items, who["james"].kind) == (("sarah",), ALL)
    # Paul has no row, so his is the default: ANY_1_OF everyone but counselors and directors
    assert who["paul"].kind == ANY and who["paul"].n == 1
    everyone = set(dataset.staff_categories["all"])
    assert set(who["paul"].items) == everyone - {"dylan", "james", "paul", "david", "lisa"}


def test_a_mapping_is_a_set_among_sets(dataset):
    text = "REQUEST ALL_OF {staff.office - mappings.buddy(staff.dylan)} FREE DURING blocks.evening"
    (copy,) = resolve(dataset, text)
    office = dataset.staff_categories["office"]
    assert set(copy.statements[0].who.items) == office - {"alan"}


@pytest.mark.parametrize(
    ("skedge", "message"),
    [
        (
            BUDDY.format(who="ALL_OF {staff.all - mappings.buddy(c)}"),
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
            "PREFER staff.all DO activities.clinics.all MAXIMIZE mappings.buddy(staff.dylan)",
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
    copies = resolve(dataset, "REQUEST EACH_OF activities.cabin_acts.all DURING blocks.cabin_act")
    days = [dataset.activities[c.statements[0].what.items[0]].day for c in copies]
    assert days == [dataset.target]
    week = resolve(
        dataset,
        "REQUEST EACH_OF activities.cabin_acts.all DURING blocks.cabin_act "
        "ON EACH_OF {2026-09-14 .. 2026-09-18}",
    )
    assert len(week) == 3  # Monday's, Wednesday's and Friday's; the 28th is another week
