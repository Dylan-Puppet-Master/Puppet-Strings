from datetime import date

from puppet_strings.model import Priority, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.validate import validate_request


def resolve(dataset, skedge, priority=Priority.HIGH):
    return validate_request(Request("t", "", skedge, priority), dataset)


def test_defaults(dataset):
    (copy,) = resolve(dataset, "DURING block.clinic_1\nTASK 'a'")[2:3]  # the target-date copy
    (statement,) = copy.statements
    assert statement.on.items == (date(2026, 9, 15),) or statement.on.items[0] in dataset.calendar
    assert statement.across.items == tuple(sorted(dataset.staff))
    assert statement.across.quantifier.kind == "ANY"
    copies = resolve(dataset, "DURING block.clinic_1\nTASK 'a'")
    assert [c.statements[0].on.items[0] for c in copies] == list(dataset.session_dates)
    assert all(c.key == "" for c in copies)


def test_each_expansion_and_keys(dataset):
    copies = resolve(
        dataset, "ON date.target\nACROSS EACH staff.counselor\nDURING block.clinic_1\nTASK 'a'"
    )
    assert [c.key for c in copies] == ["dylan", "james", "paul"]
    assert copies[0].statements[0].across.items == ("dylan",)
    product = resolve(
        dataset,
        "ON date.target\nACROSS EACH staff.director\nDURING EACH {block.clinic_1 + block.clinic_2}\nTASK 'a'",
    )
    assert [c.key for c in product] == [
        "david,clinic_1",
        "david,clinic_2",
        "lisa,clinic_1",
        "lisa,clinic_2",
    ]


def test_shared_each_applies_to_every_verb(dataset):
    copies = resolve(
        dataset,
        "ON date.target\nACROSS EACH staff.counselor\n"
        "TASK 'a' DURING {block.clinic_1 OR block.clinic_2} AS m\n"
        "TASK 'a' DURING {block.clinic_3 OR block.clinic_4} AS n\nGAP m n <= 5h",
    )
    dylan = copies[0]
    assert all(s.across.items == ("dylan",) for s in dylan.statements)
    assert dylan.statements[0].during.alternatives == (
        frozenset({"clinic_1"}),
        frozenset({"clinic_2"}),
    )
    assert dylan.gaps[0].minutes == 300


def test_or_and_alternatives(dataset):
    (copy,) = resolve(
        dataset,
        "ON date.target\nDURING block.any\nACROSS {staff.james OR (staff.dylan AND staff.paul)}\nTASK 'x'",
    )
    across = copy.statements[0].across
    assert across.alternatives == (frozenset({"james"}), frozenset({"dylan", "paul"}))
    assert across.items == ("dylan", "james", "paul")
    assert not across.single


def test_set_operators(dataset):
    (copy,) = resolve(
        dataset,
        "ON date.target\nDURING block.any\nACROSS {staff.all - staff.director - staff.counselor}\nTASK 'x'",
    )
    pool = set(copy.statements[0].across.items)
    assert pool == set(dataset.staff) - {"david", "lisa", "dylan", "james", "paul"}
    (copy,) = resolve(
        dataset,
        "ON date.target\nDURING block.any\nACROSS {staff.counselor & staff.ropes_level_2}\nTASK 'x'",
    )
    assert copy.statements[0].across.items == ()


def test_date_windows(dataset):
    (copy,) = resolve(dataset, "ON date.target - 6d .. date.target\nDURING block.any\nTASK 'x'")
    assert copy.statements[0].on.items == tuple(dataset.session_dates[:4])
    (copy,) = resolve(
        dataset, "ON date.target + 1d .. date.target + 10d\nDURING block.any\nTASK 'x'"
    )
    assert copy.statements[0].on.items == tuple(dataset.session_dates[4:])
    (copy,) = resolve(dataset, "ON date.session\nDURING block.any\nTASK 'x'")
    assert copy.statements[0].on.items == tuple(dataset.session_dates)
    (copy,) = resolve(dataset, "ON date.friday\nDURING block.any\nTASK 'x'")
    assert copy.statements[0].on.items == (date(2026, 9, 18),)
    (copy,) = resolve(dataset, "ON 2026-10-01\nDURING block.any\nTASK 'x'")
    assert copy.statements[0].on.items == ()


def test_quantifiers_and_groups(dataset):
    (copy,) = resolve(dataset, "ON date.target\nDURING 3 OF block.any_clinic\nTASK 'break'")
    during = copy.statements[0].during
    assert during.quantifier == ast.Quantifier("OF", 3)
    assert during.items == ("clinic_1", "clinic_2", "clinic_3", "clinic_4")
    (copy,) = resolve(
        dataset, "ON date.target\nDURING ALL block.any\nACROSS staff.dylan\nTASK FREE"
    )
    assert copy.statements[0].during.quantifier.kind == "ALL"
    assert set(copy.statements[0].during.items) == set(dataset.blocks)


def test_roles_and_metrics(dataset):
    (copy,) = resolve(
        dataset,
        "ON date.target\nDURING block.any_clinic\nACROSS staff.dylan\n"
        "TASK activity.candle_making ROLE role.trainee FOR 2h CONTINUOUS",
    )
    s = copy.statements[0]
    assert s.role.items == ("trainee",) and s.minutes == 120 and s.continuous
    (copy,) = resolve(
        dataset, "DURING block.any_clinic\nPREFER activity.any_clinic ~ metric.enjoyment"
    )[:1]
    assert copy.statements[0].metric == "enjoyment"
    assert set(copy.statements[0].target.items) == set(dataset.activities)
