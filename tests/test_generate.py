from datetime import date

from puppet_strings.generate import generated_requests, is_generated, is_imported, with_offerings
from puppet_strings.model import Priority, Request
from puppet_strings.skedge.validate import validate_request


def test_generated_requests_cover_every_offering(dataset):
    generated = generated_requests(dataset)
    assert len(generated) == len(dataset.offerings) == 24
    double = next(r for r in generated if "pole_course" in r.id)
    assert double.id == "offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1"
    assert double.skedge == (
        "REQUEST activities.clinics.pole_course_explore_level_1_2_dbl "
        "DURING ALL {blocks.clinic_1 + blocks.clinic_2} ON 2026-09-16"
    )
    assert double.priority is Priority.CLINIC and double.tags == ("clinic_import",)
    assert double.created == date(2026, 9, 16)


def test_a_generated_request_names_no_staff(dataset):
    """Who may run a clinic is its positions' skills, so the request says only what and when."""
    by_id = {r.id: r for r in generated_requests(dataset)}
    two = by_id["offering:2026-09-16:gravity_zip_line:clinic_1"]
    assert two.skedge == (
        "REQUEST activities.clinics.gravity_zip_line DURING blocks.clinic_1 ON 2026-09-16"
    )
    assert "staff." not in two.skedge and "AS_ROLE" not in two.skedge


def test_a_generated_request_still_fills_every_position(dataset):
    """Naming no role asks that the clinic runs, and a running clinic fills all of them."""
    from dataclasses import replace

    from puppet_strings.config import Config
    from puppet_strings.solver.solve import solve

    water = {r.id: r for r in generated_requests(dataset)}["offering:2026-09-16:canoe_1_2:clinic_1"]
    only = replace(dataset, requests=(replace(water, priority=Priority.MUST_HAPPEN),))
    result = solve(only, Config(tier_seconds_limit=10, workers=4))
    assert result.feasible
    filled = sorted(a.role for a in result.assignments if a.activity == "canoe_1_2")
    assert filled == ["first", "lifeguard"]


def test_a_generated_request_is_one_copy_not_one_per_position(dataset):
    """One row in the report per clinic instance, because its positions fill together."""
    two = {r.id: r for r in generated_requests(dataset)}[
        "offering:2026-09-16:gravity_zip_line:clinic_1"
    ]
    copies = validate_request(two, dataset)
    assert [copy.key for copy in copies] == [""]
    assert copies[0].statements[0].role is None


def test_every_generated_request_validates(dataset):
    for request in generated_requests(dataset):
        validate_request(request, dataset)


def test_a_saved_clinic_is_read_in_place_of_the_one_made(dataset):
    from dataclasses import replace

    built = dataset
    made = generated_requests(built)
    edited = replace(made[0], description="edited")
    mine = Request("mine", "", "x", Priority.HIGH)
    requests = with_offerings(replace(built, requests=(edited, mine)))
    assert [r.id for r in requests].count(made[0].id) == 1
    assert requests[0].description == "edited" and len(requests) == len(made) + 1


def test_which_requests_are_imported():
    tag = ("clinic_import",)
    clinic = Request("offering:2026-09-16:riflery:clinic_3", "", "x", Priority.CLINIC, tags=tag)
    assert is_imported(clinic) and is_generated(clinic, date(2026, 9, 16))
    assert not is_generated(clinic, date(2026, 9, 17))
    assert not is_imported(Request("mine", "", "x", Priority.HIGH, tags=tag))
