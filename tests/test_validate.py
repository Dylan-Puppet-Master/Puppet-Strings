import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.validate import validate_request


def request(skedge, priority=Priority.HIGH, weight=1.0):
    return Request("t", "", skedge, priority, weight)


@pytest.mark.parametrize(
    ("skedge", "priority", "message", "line", "column"),
    [
        ("DURING block.nope\nTASK FREE", Priority.HIGH, "unknown block name 'nope'", 1, 8),
        ("DURING staff.dylan\nTASK FREE", Priority.HIGH, "expected a block name", 1, 8),
        ("ACROSS staff.dylan\nTASK FREE", Priority.HIGH, "TASK needs DURING", 2, 1),
        (
            "DURING ANY {block.clinic_1 OR block.clinic_2}\nTASK FREE",
            Priority.HIGH,
            "a quantifier cannot apply to an expression with OR or AND",
            1,
            8,
        ),
        (
            "DURING ALL block.any_clinic\nFORBID activity.riflery",
            Priority.HIGH,
            "FORBID takes no ALL or OF",
            1,
            8,
        ),
        (
            "DURING block.any_clinic\nPREFER activity.riflery",
            Priority.MUST_HAPPEN,
            "PREFER cannot be MUST_HAPPEN",
            2,
            1,
        ),
        (
            "DURING block.any_clinic\nAVOID activity.riflery PER staff BEYOND 0",
            Priority.HIGH,
            "BEYOND must be at least 1",
            2,
            24,
        ),
        (
            "DURING block.any_clinic\nTASK activity.riflery PER staff BEYOND 1",
            Priority.HIGH,
            "PER ... BEYOND is only for AVOID",
            2,
            23,
        ),
        (
            "DURING block.any_clinic\nAVOID activity.riflery PER staff BEYOND 1 ~ metric.enjoyment",
            Priority.HIGH,
            "~ cannot combine with PER",
            2,
            43,
        ),
        (
            "DURING block.any_clinic\nTASK activity.riflery ~ metric.enjoyment",
            Priority.HIGH,
            "~ is only for PREFER and AVOID",
            2,
            23,
        ),
        (
            "DURING ALL block.any_clinic\nTASK 'x' FOR 2h",
            Priority.HIGH,
            "FOR cannot combine with DURING ALL",
            2,
            10,
        ),
        (
            "DURING block.clinic_1\nACROSS ALL staff.counselor\nTASK activity.gravity_zip_line",
            Priority.HIGH,
            "ACROSS must be a plain pool",
            2,
            8,
        ),
        (
            "ON date.session - 1d\nDURING block.clinic_1\nTASK FREE",
            Priority.HIGH,
            "needs a single date",
            1,
            4,
        ),
        (
            "DURING block.clinic_1\nTASK 'a' AS x\nGAP x y <= 1h",
            Priority.HIGH,
            "undefined label 'y'",
            3,
            1,
        ),
        (
            "DURING block.clinic_1\nTASK 'a' AS x\nTASK 'b' AS x",
            Priority.HIGH,
            "label 'x' defined twice",
            3,
            10,
        ),
        (
            "DURING block.clinic_1\nTASK 'a' DURING block.clinic_2",
            Priority.HIGH,
            "DURING is given here and on a shared line",
            2,
            10,
        ),
        (
            "DURING block.clinic_1\nTASK 'a' ROLE role.first",
            Priority.HIGH,
            "ROLE needs an activity target",
            2,
            10,
        ),
        ("DURING block.clinic_1\nFORBID FREE", Priority.HIGH, "FORBID FREE", 2, 1),
        (
            "DURING {block.clinic_1 AND block.clinic_2}\nAVOID activity.riflery",
            Priority.HIGH,
            "AND belongs in ACROSS",
            1,
            8,
        ),
        (
            "DURING block.any_clinic\nACROSS {staff.james AND staff.paul}\n"
            "PREFER {activity.riflery AND activity.archery_1_2}",
            Priority.HIGH,
            "AND belongs in ACROSS",
            3,
            8,
        ),
        (
            "DURING 3 OF block.any_clinic\nTASK 'a' AS x\nTASK 'b' AS y\nGAP x y >= 0m",
            Priority.HIGH,
            "GAP tasks must occupy a single block",
            4,
            1,
        ),
        (
            "DURING 9 OF block.any_clinic\nTASK 'a'",
            Priority.HIGH,
            "9 OF a set of 4",
            1,
            8,
        ),
        ("ON 2026-09-14\nAS x\nDURING block.clinic_1\nTASK 'a'", Priority.HIGH, "AS belongs", 2, 1),
        (
            "DURING block.clinic_1\nAVOID FREE PER staff nope BEYOND 1",
            Priority.HIGH,
            "PER fields",
            2,
            12,
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
        validate_request(request("DURING block.clinic_1\nTASK 'a'", weight=0), dataset)
    with pytest.raises(SkedgeError, match="not allowed with MUST_HAPPEN"):
        validate_request(
            request("DURING block.clinic_1\nTASK 'a'", Priority.MUST_HAPPEN, 2), dataset
        )


def test_fixture_requests_all_validate(dataset):
    for r in dataset.requests:
        assert validate_request(r, dataset)
