from datetime import date

from puppet_strings.app.facets import facets
from puppet_strings.model import Priority, Request


def req(skedge, priority=Priority.HIGH):
    return Request("r", "", skedge, priority)


DO = "REQUEST {who} DO 'a' DURING block.clinic_1"


def test_scopes(dataset):
    cases = {
        DO.format(who="staff.dylan"): "season",
        DO.format(who="staff.dylan") + " ON ALL_OF date.season.all": "season",
        DO.format(who="staff.dylan") + " ON ALL_OF date.session.all": "session",
        DO.format(who="staff.dylan") + " ON ANY_1_OF {(date.target - 6d) .. date.target}": "week",
        DO.format(who="staff.dylan") + " ON EACH_OF date.session.fridays": "week",
        DO.format(who="staff.dylan") + " ON 2026-09-16": "day",
        DO.format(who="staff.dylan") + " ON date.target": "day",
        "PREFER AT_MOST 8 EACH_OF staff.all DOING activity.all ON date.session.all": "session",
    }
    for skedge, expected in cases.items():
        assert facets(req(skedge), dataset).scope == expected, skedge
    pin = "REQUEST staff.dylan DO activity.riflery AS_ROLE role.first DURING block.clinic_1 ON 2026-09-16"
    assert facets(req(pin, Priority.MUST_HAPPEN), dataset).scope == "pin"
    assert facets(req(pin, Priority.HIGH), dataset).scope == "day"
    each = DO.format(who="EACH_OF staff.counselor") + " ON 2026-09-16"
    assert facets(req(each, Priority.MUST_HAPPEN), dataset).scope == "day"
    forbid = "REQUEST staff.dylan NOT DO activity.ropes ON 2026-09-16"
    assert facets(req(forbid, Priority.MUST_HAPPEN), dataset).scope == "pin"


def test_facets_collect_staff_activities_dates(dataset):
    f = facets(
        req(
            "REQUEST ANY_1_OF staff.counselor DO activity.riflery DURING block.clinic_1 ON date.target"
        ),
        dataset,
    )
    assert f.valid
    assert f.staff == {"dylan", "james", "paul"}
    assert f.activities == {"riflery"}
    assert f.dates == {date(2026, 9, 16)}
    assert facets(req(DO.format(who="staff.dylan")), dataset).dates == set(dataset.calendar)
    g = facets(
        req("PREFER AT_MOST 1 staff.dylan DOING activity.weapons ON date.session.fridays"), dataset
    )
    assert g.activities == {"archery_1_2", "riflery", "muay_thai"} and g.dates == {
        date(2026, 9, 18),
        date(2026, 9, 25),
    }


def test_invalid_request_keeps_its_error(dataset):
    f = facets(req("REQUEST staff.dylan DO 'a'"), dataset)
    assert not f.valid and "needs DURING" in f.error
    assert f.staff == frozenset()
