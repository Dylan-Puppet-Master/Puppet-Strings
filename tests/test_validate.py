import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.validate import validate_request


def request(skedge, priority=Priority.HIGH, weight=1.0):
    return Request("t", "", skedge, priority, weight)


DO = "REQUEST staff.dylan DO 'x' DURING block.clinic_1"


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
            "REQUEST staff.counselor DO 'x' DURING block.clinic_1",
            Priority.HIGH,
            "needs a quantifier: ALL_OF, ANY_n_OF or EACH_OF",
            1,
            9,
        ),
        (
            "REQUEST ANY_1_OF staff.dylan DO 'x' DURING block.clinic_1",
            Priority.HIGH,
            "is one item and takes no quantifier",
            1,
            9,
        ),
        (
            "REQUEST staff.dylan DO ALL_OF activity.all DURING block.clinic_1",
            Priority.HIGH,
            "one activity at a time",
            1,
            24,
        ),
        (
            "REQUEST staff.dylan DO activity.riflery AS_ROLE ANY_2_OF {role.first + role.second} DURING block.clinic_1",
            Priority.HIGH,
            "one activity at a time",
            1,
            49,
        ),
        ("REQUEST staff.dylan DO 'x'", Priority.HIGH, "needs DURING", 1, 1),
        (f"{DO} DURING block.clinic_2", Priority.HIGH, "DURING given twice", 1, 50),
        (
            f"IF staff.dylan FREE\nUNLESS staff.rob FREE\n{DO}",
            Priority.HIGH,
            "only one IF or UNLESS per declaration",
            2,
            1,
        ),
        (f"PREFER AT_MOST 1 staff.all DOING 'x'\n{DO}", Priority.HIGH, "PREFER stands alone", 1, 1),
        (
            "REQUEST staff.dylan DO 'x' DURING block.nope",
            Priority.HIGH,
            "unknown block name 'nope'",
            1,
            35,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING staff.rob",
            Priority.HIGH,
            "expected a block name",
            1,
            35,
        ),
        ("REQUEST s DO 'x' DURING block.clinic_1", Priority.HIGH, "unknown variable 's'", 1, 9),
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
            "expected a block name, not 's'",
            2,
            25,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING {block.clinic_1 + block.clinic_2 & block.meals}",
            Priority.HIGH,
            "mixed set operators need parentheses",
            1,
            68,
        ),
        (
            "REQUEST staff.dylan DO 'x' AS_ROLE role.first DURING block.clinic_1",
            Priority.HIGH,
            "AS_ROLE needs an activity",
            1,
            28,
        ),
        (
            "REQUEST staff.dylan FREE AS_ROLE role.first DURING block.clinic_1",
            Priority.HIGH,
            "AS_ROLE needs an activity",
            1,
            26,
        ),
        (
            "REQUEST staff.dylan DO activity.riflery FOR 1h DURING block.clinic_1",
            Priority.HIGH,
            "FOR needs a quoted task",
            1,
            41,
        ),
        (
            "REQUEST staff.dylan FREE DURING block.clinic_1 WITH staff.rob",
            Priority.HIGH,
            "FREE has no instance",
            1,
            48,
        ),
        (
            "REQUEST AT_LEAST 1 staff.all NOT FREE WITHOUT staff.rob",
            Priority.HIGH,
            "FREE has no instance",
            1,
            39,
        ),
        (
            "REQUEST AT_LEAST 0 staff.all DOING 'x'",
            Priority.HIGH,
            "amount must be at least 1",
            1,
            9,
        ),
        ("REQUEST AT_MOST 0 staff.all DOING 'x'", Priority.HIGH, "write NOT DO", 1, 9),
        ("PREFER EXACTLY 0m staff.all DOING 'x'", Priority.HIGH, "write NOT DO", 1, 8),
        (
            "PREFER EACH_OF s IN staff.all DOING activity.all MAXIMIZE metric.preference(s)",
            Priority.HIGH,
            "metric arguments do not match its keys",
            1,
            1,
        ),
        (
            "PREFER staff.all DOING activity.all MAXIMIZE metric.preference(staff.counselor, activity.riflery)",
            Priority.HIGH,
            "metric argument must be one item",
            1,
            64,
        ),
        (
            "ANY_1_OF s IN staff.all\nPREFER s DOING activity.all MAXIMIZE metric.preference(s, activity.riflery)",
            Priority.HIGH,
            "metric argument must be one item",
            2,
            56,
        ),
        (
            "PREFER AT_MOST 1 staff.all DOING 'x'",
            Priority.MUST_HAPPEN,
            "PREFER cannot be MUST_HAPPEN",
            1,
            1,
        ),
        (
            f"a: {DO}\nb: REQUEST staff.dylan DO 'y' DURING block.clinic_2\nGAP a TO b AT_LEAST 3",
            Priority.HIGH,
            "GAP needs a duration",
            3,
            12,
        ),
        (
            "a: REQUEST staff.dylan FREE DURING block.clinic_1",
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
            61,
        ),
        (f"{DO} ON {{date.session.all - 1d}}", Priority.HIGH, "needs a single date here", 1, 54),
        (f"{DO} ON 2026-13-01", Priority.HIGH, "invalid date", 1, 53),
        (
            "REQUEST staff.dylan DO 'x' DURING ANY_1_OF block.all ON date.session.third_thursday",
            Priority.HIGH,
            "unknown date name 'session.third_thursday'",
            1,
            57,
        ),
        (
            "ANY_1_OF b IN block.all\nREQUEST staff.dylan DO 'x' DURING {b + block.lunch}",
            Priority.HIGH,
            "must stand alone",
            2,
            36,
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
    text = f"a: {DO}\nb: REQUEST staff.dylan DO 'y' DURING block.clinic_2\nGAP a TO b AT_LEAST 0m"
    assert validate_request(request(text), dataset)
