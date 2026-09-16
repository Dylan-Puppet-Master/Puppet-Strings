from datetime import date

from puppet_strings.app.facets import facets
from puppet_strings.model import Priority, Request


def req(skedge, priority=Priority.HIGH):
    return Request("r", "", skedge, priority)


def test_scopes(dataset):
    cases = {
        "DURING block.clinic_1\nTASK 'a'": "season",
        "ON date.session\nDURING block.clinic_1\nTASK 'a'": "session",
        "ON date.target - 6d .. date.target\nDURING block.clinic_1\nTASK 'a'": "week",
        "ON date.friday\nDURING block.clinic_1\nTASK 'a'": "week",
        "ON 2026-09-16\nDURING block.clinic_1\nTASK 'a'": "day",
        "ON date.target\nDURING block.clinic_1\nACROSS staff.dylan\nTASK 'a'": "day",
    }
    for skedge, expected in cases.items():
        assert facets(req(skedge), dataset).scope == expected, skedge
    pin = "ON 2026-09-16\nDURING block.clinic_1\nACROSS staff.dylan\nTASK activity.riflery ROLE role.first"
    assert facets(req(pin, Priority.MUST_HAPPEN), dataset).scope == "pin"
    assert facets(req(pin, Priority.HIGH), dataset).scope == "day"
    category = "ON 2026-09-16\nDURING block.clinic_1\nACROSS staff.counselor\nTASK 'a'"
    assert (
        facets(req(category, Priority.MUST_HAPPEN), dataset).scope == "pin"
    )  # a category is one ref
    each = "ON 2026-09-16\nDURING block.clinic_1\nACROSS EACH staff.counselor\nTASK 'a'"
    assert facets(req(each, Priority.MUST_HAPPEN), dataset).scope == "day"


def test_facets_collect_staff_activities_dates(dataset):
    f = facets(
        req("ON date.target\nDURING block.clinic_1\nACROSS staff.counselor\nTASK activity.riflery"),
        dataset,
    )
    assert f.valid
    assert f.staff == {"dylan", "james", "paul"}
    assert f.activities == {"riflery"}
    assert f.dates == {date(2026, 9, 16)}


def test_invalid_request_keeps_its_error(dataset):
    f = facets(req("TASK 'a'"), dataset)
    assert not f.valid and "needs DURING" in f.error
    assert f.staff == frozenset()
