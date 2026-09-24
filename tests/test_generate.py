from datetime import date

from puppet_strings.generate import (
    generated_requests,
    has_offerings_loaded,
    import_if_missing,
    merge,
)
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
    result = solve(only, Config(time_limit_seconds=10, workers=4))
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


def test_merge_drops_the_dates_old_generated_requests_and_keeps_the_rest():
    tag = ("clinic_import",)
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


class _Book:
    def __init__(self):
        self.put_calls = []

    def put(self, requests):
        self.put_calls.append(list(requests))


def test_import_if_missing_imports_a_day_with_none(dataset):
    from dataclasses import replace

    bare = replace(
        dataset, requests=tuple(r for r in dataset.requests if "clinic_import" not in r.tags)
    )
    book = _Book()
    imported, count = import_if_missing(bare, book)
    assert count == len(dataset.offerings) == len(book.put_calls[0])
    assert has_offerings_loaded(imported.requests, dataset.target)


def test_import_if_missing_leaves_a_day_that_has_some(dataset):
    book = _Book()
    assert import_if_missing(dataset, book) == (dataset, 0) and not book.put_calls


def test_import_if_missing_skips_an_empty_offerings_tab(dataset):
    from dataclasses import replace

    empty = replace(dataset, requests=(), offerings=())
    book = _Book()
    assert import_if_missing(empty, book) == (empty, 0) and not book.put_calls
