from datetime import date

from puppet_strings.app.facets import facets
from puppet_strings.model import Priority, Request


def req(skedge, priority=Priority.HIGH):
    return Request("r", "", skedge, priority)


DO = "REQUEST {who} DO 'a' DURING blocks.clinic_1"


def test_a_request_about_no_calendar_date_covers_nothing(dataset):
    """Off-calendar dates once read as "every day"; an empty date set is what it is."""
    off = "REQUEST staff.dylan DO 'a' DURING blocks.clinic_1 ON 2026-11-17"
    f = facets(req(off), dataset)
    assert f.valid and f.dates == frozenset() and not f.covers(dataset.target)


def test_facets_collect_staff_activities_dates(dataset):
    f = facets(
        req(
            "REQUEST ANY 1 staff.counselor DO activities.clinics.riflery DURING blocks.clinic_1 ON dates.target"
        ),
        dataset,
    )
    assert f.valid
    assert f.staff == {"dylan", "james", "paul"}
    assert f.activities == {"riflery"}
    assert f.dates == {date(2026, 9, 16)}
    assert facets(req(DO.format(who="staff.dylan")), dataset).dates == set(dataset.calendar)
    g = facets(
        req(
            "PREFER AT_MOST 1 staff.dylan DO activities.clinics.weapons ON dates.session.one.fridays"
        ),
        dataset,
    )
    assert g.activities == {"archery_1_2", "riflery", "muay_thai"} and g.dates == {
        date(2026, 9, 18),
        date(2026, 9, 25),
    }


def test_invalid_request_keeps_its_error(dataset):
    f = facets(req("REQUEST staff.dylan DO 'a'"), dataset)
    assert not f.valid and "needs DURING" in f.error
    assert f.staff == frozenset()
