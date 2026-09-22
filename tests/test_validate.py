import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.validate import validate_request


def request(skedge, priority=Priority.HIGH, weight=1.0):
    return Request("t", "", skedge, priority, weight)


DO = "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1"


@pytest.mark.parametrize(
    ("skedge", "priority", "message", "line", "column"),
    [
        (
            "EACH_OF s IN staff.all",
            Priority.HIGH,
            "a declaration needs at least one statement",
            1,
            1,
        ),
        (
            "REQUEST staff.counselor DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF",
            1,
            9,
        ),
        (
            "REQUEST ANY_1_OF staff.dylan DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "is one item and takes no quantifier",
            1,
            9,
        ),
        (
            "REQUEST staff.dylan DO ALL_OF activities.clinics.all DURING blocks.clinic_1",
            Priority.HIGH,
            "one activity at a time",
            1,
            24,
        ),
        (
            "REQUEST staff.dylan DO activities.clinics.riflery AS_ROLE ANY_2_OF {roles.first + roles.second} DURING blocks.clinic_1",
            Priority.HIGH,
            "one activity at a time",
            1,
            59,
        ),
        ("REQUEST staff.dylan DO 'x'", Priority.HIGH, "needs DURING", 1, 1),
        (f"{DO} DURING blocks.clinic_2", Priority.HIGH, "DURING given twice", 1, 51),
        (
            f"IF staff.dylan FREE\nUNLESS staff.rob FREE\n{DO}",
            Priority.HIGH,
            "only one IF or UNLESS per declaration",
            2,
            1,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING blocks.nope",
            Priority.HIGH,
            "unknown name 'blocks.nope'",
            1,
            35,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING staff.rob",
            Priority.HIGH,
            "expected a name from blocks",
            1,
            35,
        ),
        ("REQUEST s DO 'x' DURING blocks.clinic_1", Priority.HIGH, "unknown variable 's'", 1, 9),
        (
            f"EACH_OF s IN staff.all\nEACH_OF s IN staff.all\n{DO}",
            Priority.HIGH,
            "variable bound twice",
            2,
            1,
        ),
        (
            "EACH_OF s IN staff.all\nREQUEST s DO 'x' DURING s",
            Priority.HIGH,
            "expected a name from blocks, not 's'",
            2,
            25,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING {blocks.clinic_1 + blocks.clinic_2 & blocks.meals}",
            Priority.HIGH,
            "mixed set operators need parentheses",
            1,
            70,
        ),
        (
            "REQUEST staff.dylan DO 'x' AS_ROLE roles.first DURING blocks.clinic_1",
            Priority.HIGH,
            "AS_ROLE needs an activity",
            1,
            28,
        ),
        (
            "REQUEST staff.dylan FREE AS_ROLE roles.first DURING blocks.clinic_1",
            Priority.HIGH,
            "AS_ROLE needs an activity",
            1,
            26,
        ),
        (
            "REQUEST staff.dylan DO activities.clinics.riflery FOR 1h DURING blocks.clinic_1",
            Priority.HIGH,
            "FOR needs a quoted task",
            1,
            51,
        ),
        (
            "REQUEST staff.dylan FREE DURING blocks.clinic_1 WITH staff.rob",
            Priority.HIGH,
            "FREE has no instance",
            1,
            49,
        ),
        (
            "REQUEST AT_LEAST 1 staff.all NOT FREE WITHOUT staff.rob",
            Priority.HIGH,
            "FREE has no instance",
            1,
            39,
        ),
        (
            "REQUEST AT_LEAST 0 staff.all DO 'x'",
            Priority.HIGH,
            "amount must be at least 1",
            1,
            9,
        ),
        ("REQUEST AT_MOST 0 staff.all DO 'x'", Priority.HIGH, "write NOT DO", 1, 9),
        ("PREFER EXACTLY 0m staff.all DO 'x'", Priority.HIGH, "write NOT DO", 1, 8),
        (
            "PREFER EACH_OF s IN staff.all DO activities.clinics.all MAXIMIZE metrics.preference(s)",
            Priority.HIGH,
            "metric arguments do not match its keys",
            1,
            1,
        ),
        (
            "PREFER staff.all DO activities.clinics.all MAXIMIZE metrics.preference(staff.counselor, activities.clinics.riflery)",
            Priority.HIGH,
            "metric argument must be one item",
            1,
            72,
        ),
        (
            "ANY_1_OF s IN staff.all\nPREFER s DO activities.clinics.all MAXIMIZE metrics.preference(s, activities.clinics.riflery)",
            Priority.HIGH,
            "metric argument must be one item",
            2,
            64,
        ),
        (
            "PREFER AT_MOST 1 staff.all DO 'x'",
            Priority.MUST_HAPPEN,
            "PREFER needs a priority it can be weighed at",
            1,
            1,
        ),
        (
            f"a: {DO}\nb: REQUEST staff.dylan DO 'y' DURING blocks.clinic_2\nGAP a TO b AT_LEAST 3",
            Priority.HIGH,
            "GAP needs a duration",
            3,
            12,
        ),
        (
            "a: REQUEST staff.dylan FREE DURING blocks.clinic_1",
            Priority.HIGH,
            "only REQUEST … DO can be labeled",
            1,
            4,
        ),
        (
            "a: REQUEST staff.dylan NOT DO 'x'",
            Priority.HIGH,
            "only REQUEST … DO can be labeled",
            1,
            4,
        ),
        (f"a: {DO}\nGAP a TO b AT_LEAST 0m", Priority.HIGH, "undefined label 'b'", 2, 1),
        (f"a: {DO}\na: {DO}", Priority.HIGH, "label 'a' defined twice", 2, 4),
        (
            f"{DO} ON ALL_OF {{2026-09-18 .. 2026-09-14}}",
            Priority.HIGH,
            "date range ends before it starts",
            1,
            62,
        ),
        (
            f"{DO} ON {{dates.session.one.all - 1d}}",
            Priority.HIGH,
            "needs a single date here",
            1,
            55,
        ),
        (f"{DO} ON 2026-13-01", Priority.HIGH, "invalid date", 1, 54),
        (
            "REQUEST staff.dylan DO 'x' DURING ANY_1_OF blocks.all ON dates.session.one.week.nine.all",
            Priority.HIGH,
            "unknown name 'dates.session.one.week.nine.all'",
            1,
            58,
        ),
        (
            "ANY_1_OF b IN blocks.all\nREQUEST staff.dylan DO 'x' DURING {blocks.all - b}",
            Priority.HIGH,
            "chosen by the solver",
            2,
            49,
        ),
        (
            "ANY_1_OF p IN staff.all\nREQUEST ANY_2_OF {staff.dylan + p} DO 'x' DURING blocks.lunch",
            Priority.HIGH,
            "taken with ALL_OF or not at all",
            2,
            9,
        ),
    ],
)
def test_rejected(dataset, skedge, priority, message, line, column):
    with pytest.raises(SkedgeError) as info:
        validate_request(request(skedge, priority), dataset)
    assert message in info.value.message
    assert (info.value.line, info.value.column) == (line, column)


def test_weight_rules(dataset):
    with pytest.raises(SkedgeError, match="weight must be positive"):
        validate_request(request(DO, weight=0), dataset)
    with pytest.raises(SkedgeError, match="not allowed with MUST_HAPPEN"):
        validate_request(request(DO, Priority.MUST_HAPPEN, 2), dataset)


def test_fixture_requests_all_validate(dataset):
    for r in dataset.requests:
        assert validate_request(r, dataset)


def test_a_gap_may_be_zero(dataset):
    text = f"a: {DO}\nb: REQUEST staff.dylan DO 'y' DURING blocks.clinic_2\nGAP a TO b AT_LEAST 0m"
    assert validate_request(request(text), dataset)


EXCLUDE = "EXCLUDE staff.dylan DO 'offsite' DURING ALL_OF blocks.all ON dates.target"


def test_an_exclusion_validates(dataset):
    assert validate_request(request(EXCLUDE, Priority.MUST_HAPPEN), dataset)
    assert validate_request(
        request("EXCLUDE staff.dylan DO 'offsite'", Priority.MUST_HAPPEN), dataset
    )


@pytest.mark.parametrize(
    ("skedge", "priority", "message"),
    [
        (EXCLUDE, Priority.HIGH, "EXCLUDE is a fact about the day, so it is MUST_HAPPEN"),
        (
            "EXCLUDE ANY_1_OF staff.all DO 'offsite'",
            Priority.MUST_HAPPEN,
            "nothing in it is ANY_n_OF",
        ),
        (
            "EXCLUDE staff.dylan DO 'offsite' DURING ANY_2_OF blocks.all",
            Priority.MUST_HAPPEN,
            "nothing in it is ANY_n_OF",
        ),
        (
            f"{EXCLUDE}\nREQUEST staff.rob DO 'x' DURING blocks.clinic_1",
            Priority.MUST_HAPPEN,
            "EXCLUDE stands on its own line and its own request",
        ),
        (
            "EXCLUDE staff.dylan DO 'offsite' FOR 30m",
            Priority.MUST_HAPPEN,
            "EXCLUDE takes DURING and ON, not FOR",
        ),
        (
            "EXCLUDE staff.dylan DO 'offsite' ON dates.target ON dates.target",
            Priority.MUST_HAPPEN,
            "ON given twice",
        ),
        (
            "EXCLUDE staff.counselor DO 'offsite'",
            Priority.MUST_HAPPEN,
            "needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF",
        ),
    ],
)
def test_an_exclusion_is_refused(dataset, skedge, priority, message):
    with pytest.raises(SkedgeError) as info:
        validate_request(request(skedge, priority), dataset)
    assert message in info.value.message
