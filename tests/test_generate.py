from datetime import date

from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Priority, Request
from puppet_strings.skedge.validate import validate_request


def test_generated_requests_cover_every_offering(dataset):
    generated = generated_requests(dataset)
    assert len(generated) == len(dataset.offerings) == 24
    double = next(r for r in generated if "pole_course" in r.id)
    assert double.id == "offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1"
    assert double.skedge == (
        "REQUEST ANY_1_OF staff.all DO activities.clinics.pole_course_explore_level_1_2_dbl "
        "AS_ROLE EACH_OF {roles.first + roles.second + roles.third} "
        "DURING ALL_OF {blocks.clinic_1 + blocks.clinic_2} ON 2026-09-16"
    )
    assert double.priority is Priority.CLINIC and double.tags == ("generated",)
    assert double.created == date(2026, 9, 16)


def test_generated_requests_ask_for_every_position_by_role(dataset):
    """Every position named, facilitators first, then lifeguards."""
    by_id = {r.id: r for r in generated_requests(dataset)}
    two = by_id["offering:2026-09-16:gravity_zip_line:clinic_1"]
    assert two.skedge == (
        "REQUEST ANY_1_OF staff.all DO activities.clinics.gravity_zip_line "
        "AS_ROLE EACH_OF {roles.first + roles.second} DURING blocks.clinic_1 ON 2026-09-16"
    )
    water = by_id["offering:2026-09-16:canoe_1_2:clinic_1"]
    assert "AS_ROLE EACH_OF {roles.first + roles.lifeguard}" in water.skedge


def test_one_position_takes_the_role_on_its_own(dataset):
    """A one-item set takes no quantifier, so EACH_OF over one role would be rejected."""
    one = {r.id: r for r in generated_requests(dataset)}["offering:2026-09-16:riflery:clinic_3"]
    assert "AS_ROLE roles.first DURING" in one.skedge and "EACH_OF {role" not in one.skedge


def test_each_position_is_its_own_choice_of_person(dataset):
    """EACH_OF splits into one copy per position; ALL_OF would want one person in both."""
    two = {r.id: r for r in generated_requests(dataset)}[
        "offering:2026-09-16:gravity_zip_line:clinic_1"
    ]
    copies = validate_request(two, dataset)
    assert [copy.key for copy in copies] == ["first", "second"]
    assert [copy.statements[0].role.items for copy in copies] == [("first",), ("second",)]


def test_every_generated_request_validates(dataset):
    for request in generated_requests(dataset):
        validate_request(request, dataset)


def test_merge_drops_the_dates_old_generated_requests_and_keeps_the_rest():
    tag = ("generated",)
    old = Request("offering:2026-09-16:riflery:clinic_3", "old", "x", Priority.CLINIC, tags=tag)
    gone = Request("offering:2026-09-16:salsa:clinic_4", "", "x", Priority.CLINIC, tags=tag)
    other_day = Request("offering:2026-09-15:salsa:clinic_4", "", "x", Priority.CLINIC, tags=tag)
    mine = Request("mine", "", "x", Priority.HIGH)
    new = Request("offering:2026-09-16:riflery:clinic_3", "new", "y", Priority.CLINIC, tags=tag)
    merged = merge([old, gone, other_day, mine], [new], date(2026, 9, 16))
    assert [r.id for r in merged] == [other_day.id, "mine", new.id]
    assert merged[-1].description == "new"


def test_has_offerings_loaded(dataset):
    assert has_offerings_loaded(dataset.requests, date(2026, 9, 16))
    assert not has_offerings_loaded(dataset.requests, date(2026, 9, 17))
