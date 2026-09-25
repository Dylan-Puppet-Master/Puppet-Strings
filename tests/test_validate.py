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
        ("EACH s IN staff", Priority.HIGH, "a declaration needs at least one statement", 1, 1),
        (
            "REQUEST staff.dylan DO 'x' DURING ANY CONSECUTIVE blocks.all_clinics",
            Priority.HIGH,
            "ANY CONSECUTIVE pools each run of blocks for a FOR to measure",
            1,
            35,
        ),
        (
            "REQUEST staff.counselor DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "needs a quantifier: ALL, ANY, ANY n, EACH or a count",
            1,
            9,
        ),
        (
            "REQUEST AT_LEAST 2 staff.dylan DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "a count counts the members of a set, and staff.dylan is one",
            1,
            9,
        ),
        (
            "REQUEST ANY staff.dylan DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "is one item and takes no quantifier",
            1,
            9,
        ),
        (
            "REQUEST staff.dylan DO ALL activities.clinics DURING blocks.clinic_1",
            Priority.HIGH,
            "one activity at a time",
            1,
            24,
        ),
        (
            "REQUEST staff.dylan DO activities.clinics.riflery AS_ROLE AT_LEAST 2 {roles.first + roles.second} DURING blocks.clinic_1",
            Priority.HIGH,
            "one role at a time",
            1,
            51,
        ),
        (f"{DO} DURING blocks.clinic_2", Priority.HIGH, "DURING given twice", 1, 51),
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
            "REQUEST mappings.buddy(c) FREE DURING blocks.evening",
            Priority.HIGH,
            "unknown variable 'c'",
            1,
            24,
        ),
        (
            f"EACH s IN staff\nEACH s IN staff\n{DO}",
            Priority.HIGH,
            "variable bound twice",
            2,
            1,
        ),
        (
            "EACH s IN staff\nREQUEST s DO 'x' DURING s",
            Priority.HIGH,
            "expected a name from blocks, not 's'",
            2,
            25,
        ),
        (
            "REQUEST staff.dylan DO 'x' DURING {blocks.clinic_1 + blocks.clinic_2 & blocks.meals}",
            Priority.HIGH,
            "mixed set operators need braces around one side",
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
            "REQUEST staff.dylan DO activities.clinics.riflery FOR EXACTLY 1h DURING blocks.clinic_1",
            Priority.HIGH,
            "FOR on an activity, FREE or BUSY measures its time across blocks",
            1,
            51,
        ),
        (
            "REQUEST staff.dylan NOT DO activities.clinics.riflery FOR EXACTLY 1h",
            Priority.HIGH,
            "FOR needs a quoted task",
            1,
            55,
        ),
        (
            "REQUEST staff.dylan FREE DURING blocks.clinic_1 WITH staff.rob",
            Priority.HIGH,
            "FREE and BUSY have no instance",
            1,
            49,
        ),
        (
            "REQUEST AT_LEAST 1 staff BUSY WITHOUT staff.rob",
            Priority.HIGH,
            "FREE and BUSY have no instance",
            1,
            31,
        ),
        (
            "REQUEST staff.dylan NOT DO 'x' WITH EACH staff",
            Priority.HIGH,
            "WITH counts who is alongside, so it takes ALL or a count, not EACH",
            1,
            37,
        ),
        ("REQUEST AT_LEAST 0 staff DO 'x'", Priority.HIGH, "amount must be at least 1", 1, 9),
        ("REQUEST AT_MOST 0 staff DO 'x'", Priority.HIGH, "write NOT DO", 1, 9),
        (
            "PREFER EACH s IN staff DO ANY activities.clinics MAXIMIZE mappings.preference(s)",
            Priority.HIGH,
            "wrong number of arguments: mappings.preference takes (staff, activities.clinics), not 1",
            1,
            1,
        ),
        (
            "PREFER ANY staff DO ANY activities.clinics MAXIMIZE mappings.preference(staff.counselor, activities.clinics.riflery)",
            Priority.HIGH,
            "mapping argument must be one item",
            1,
            73,
        ),
        (
            "ANY 1 s IN staff\nPREFER s DO ANY activities.clinics MAXIMIZE mappings.preference(s, activities.clinics.riflery)",
            Priority.HIGH,
            "mapping argument must be one item",
            2,
            65,
        ),
        (
            "PREFER AT_MOST 1 staff DO 'x'",
            Priority.MUST_HAPPEN,
            "PREFER needs a priority it can be weighed at",
            1,
            1,
        ),
        (
            "PREFER staff.dylan DO 'x' DURING blocks.clinic_1",
            Priority.HIGH,
            "PREFER is weighed by how close it comes, so it needs a count or a FOR length",
            1,
            8,
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
        (
            "a: REQUEST staff.dylan DO 'x' DURING AT_MOST 2 blocks\nb: REQUEST staff.dylan DO 'y' DURING blocks.clinic_2\nGAP a TO b AT_LEAST 0m",
            Priority.HIGH,
            "a GAP is measured from what a REQUEST makes",
            1,
            4,
        ),
        (f"a: {DO}\nGAP a TO b AT_LEAST 0m", Priority.HIGH, "undefined label 'b'", 2, 1),
        (f"a: {DO}\na: {DO}", Priority.HIGH, "label 'a' defined twice", 2, 4),
        (
            f"{DO} ON ALL {{2026-09-18 .. 2026-09-14}}",
            Priority.HIGH,
            "date range ends before it starts",
            1,
            59,
        ),
        (f"{DO} ON {{dates.session_1 - 1d}}", Priority.HIGH, "needs a single date here", 1, 55),
        (f"{DO} ON 2026-13-01", Priority.HIGH, "invalid date", 1, 54),
        (
            "REQUEST staff.dylan DO 'x' DURING ANY 1 blocks ON dates.session_1.week_9",
            Priority.HIGH,
            "unknown name 'dates.session_1.week_9'",
            1,
            51,
        ),
        (
            "ANY 1 b IN blocks\nREQUEST staff.dylan DO 'x' DURING ALL {blocks & b}",
            Priority.HIGH,
            "chosen by the solver",
            2,
            49,
        ),
        (
            "ANY 1 p IN staff\nREQUEST ANY 2 {staff.dylan + p} DO 'x' DURING blocks.lunch",
            Priority.HIGH,
            "taken with ALL or not at all",
            2,
            9,
        ),
        (
            "REQUEST staff.rob NOT DO 'break' DURING blocks.meals",
            Priority.HIGH,
            "a set here is matched, so it takes ANY",
            1,
            41,
        ),
        (
            "REQUEST ANY staff NOT DO 'x'",
            Priority.HIGH,
            "left of NOT the subject is who the NOT is about",
            1,
            9,
        ),
        (
            "REQUEST EXACTLY 2 staff NOT DO 'x'",
            Priority.HIGH,
            "left of NOT the subject is chosen, so it takes ANY 2, not EXACTLY 2",
            1,
            9,
        ),
        (
            "REQUEST staff.rob NOT DO ANY activities.clinics.ropes WITHOUT ANY staff.mfg",
            Priority.HIGH,
            "WITHOUT counts who is alongside, so it takes ALL or a count, not ANY",
            1,
            63,
        ),
        (
            "PREFER EACH staff DO ALL activities.clinics MAXIMIZE mappings.preference(staff.dylan, activities.clinics.riflery)",
            Priority.HIGH,
            "a pattern matches one assignment at a time, so a set in it takes ANY or EACH",
            1,
            22,
        ),
        (
            "REQUEST staff.rob NOT DO 'x' DURING AT_MOST 2 blocks.all_clinics",
            Priority.HIGH,
            "right of NOT a set takes ANY, for any of these, or ALL, for all of them together",
            1,
            37,
        ),
        (
            "REQUEST staff.rob NOT DO 'x' DURING ALL blocks.clinic_1",
            Priority.HIGH,
            "is one item and takes no quantifier",
            1,
            37,
        ),
        (
            "PREFER staff.dylan DO 'x' DURING AT_MOST 1 {blocks.clinic_1 + (ANY 1 {blocks.clinic_2 + blocks.clinic_3})}",
            Priority.HIGH,
            "a group in a count is taken whole",
            1,
            63,
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


EXCLUDE = "EXCLUDE staff.dylan DO 'offsite' DURING ALL blocks ON dates.target"


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
            "EXCLUDE AT_LEAST 1 staff DO 'offsite'",
            Priority.MUST_HAPPEN,
            "nothing in it is chosen, counted or ANY",
        ),
        (
            "EXCLUDE staff.dylan DO 'offsite' DURING ANY blocks",
            Priority.MUST_HAPPEN,
            "nothing in it is chosen, counted or ANY",
        ),
        (
            f"{EXCLUDE}\nREQUEST staff.rob DO 'x' DURING blocks.clinic_1",
            Priority.MUST_HAPPEN,
            "EXCLUDE stands on its own line and its own request",
        ),
        (
            "EXCLUDE staff.dylan DO 'offsite' FOR EXACTLY 30m",
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
            "needs a quantifier: ALL, ANY, ANY n, EACH or a count",
        ),
    ],
)
def test_an_exclusion_is_refused(dataset, skedge, priority, message):
    with pytest.raises(SkedgeError) as info:
        validate_request(request(skedge, priority), dataset)
    assert message in info.value.message
