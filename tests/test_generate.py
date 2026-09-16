from datetime import date

from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Priority, Request


def test_generated_requests_cover_every_offering(dataset):
    generated = generated_requests(dataset)
    assert len(generated) == len(dataset.offerings) == 24
    double = next(r for r in generated if "pole_course" in r.id)
    assert double.id == "offering:2026-09-16:pole_course_explore_level_1_2_dbl:clinic_1"
    assert double.skedge == (
        "ON 2026-09-16\nDURING ALL {block.clinic_1 + block.clinic_2}\n"
        "TASK activity.pole_course_explore_level_1_2_dbl"
    )
    assert double.priority is Priority.CLINIC and double.tags == ("generated",)
    assert double.created == date(2026, 9, 16)


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
