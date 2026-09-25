"""Counts on the sets they count, lengths on FOR, and BUSY, as the solver keeps them."""

from datetime import timedelta

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Priority
from puppet_strings.solver.solve import solve
from tests.build import OK, TARGET, clinic, dataset, published, request, staff

CONFIG = Config(time_limit_seconds=10, workers=4)
MUST = Priority.MUST_HAPPEN
ARCHERY = clinic("Archery 1 & 2", ("Archery 1 & 2", 1), category="weapons")
CANDLE = clinic("Candle Making", ("Candle making", 1))


def run(ds):
    result = solve(ds, CONFIG)
    assert result.feasible
    return result


def rows(result, activity, who=None):
    return [a for a in result.assignments if a.activity == activity and who in (None, a.staff)]


def blocks(result, activity, who=None):
    return {a.block for a in rows(result, activity, who)}


def ids(outcomes):
    return [o.id for o in outcomes]


def test_any_one_and_not_do_the_rest_leaves_the_other_out():
    """Alesa rakes in clinic 1, so she is the one, and Dylan rakes in no block at all."""
    ds = dataset(
        [staff("Dylan"), staff("Alesa"), staff("Tori"), staff("Brian")],
        [],
        requests=[
            request(
                "one",
                "ANY 1 r IN {staff.dylan + staff.alesa}\n"
                "REQUEST r DO 'rake leaves' DURING ANY blocks\n"
                "REQUEST ALL {{staff.dylan + staff.alesa} - r} NOT DO 'rake leaves'",
                MUST,
            ),
            request("alesa", "REQUEST staff.alesa DO 'rake leaves' DURING blocks.clinic_1", MUST),
            request(
                "other",
                "ANY 1 r IN {staff.tori + staff.brian}\n"
                "REQUEST r DO 'rake leaves' DURING ANY blocks\n"
                "REQUEST ALL {{staff.tori + staff.brian} - r} NOT DO 'rake leaves'",
                MUST,
            ),
            request("dylan", "REQUEST staff.dylan DO 'rake leaves' DURING blocks.clinic_2"),
        ],
    )
    result = run(ds)
    assert not rows(result, "rake leaves", "dylan")
    assert ids(result.unsatisfied) == ["dylan"]
    raking = {a.staff for a in rows(result, "rake leaves")} - {"alesa", "dylan"}
    assert len(raking) == 1  # the other set's own one, whichever it is


def test_a_choice_under_each_is_each_persons_own():
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request("breaks", "REQUEST EACH staff DO 'break' DURING ANY 3 blocks", MUST),
            request("dylan", "REQUEST staff.dylan FREE DURING blocks.clinic_1", MUST),
            request("sarah", "REQUEST staff.sarah FREE DURING blocks.clinic_2", MUST),
        ],
    )
    result = run(ds)
    assert len(blocks(result, "break", "dylan")) >= 3
    assert len(blocks(result, "break", "sarah")) >= 3


def test_a_count_of_people_holds_in_each_block():
    members = [staff(n) for n in ("Dylan", "Sarah", "Vic", "Rob")]
    ds = dataset(
        members,
        [],
        requests=[
            request(
                "two",
                "REQUEST AT_MOST 2 staff DO 'break' DURING EACH blocks",
                MUST,
            ),
            request("all", "REQUEST EACH staff DO 'break' DURING blocks.lunch"),
        ],
    )
    result = run(ds)
    assert len([a for a in rows(result, "break") if a.block == "lunch"]) == 2
    assert len(result.unsatisfied) == 2


def test_all_makes_a_group_one_unit_and_each_splits_it():
    both = "{staff.dylan + staff.alesa}"
    together = dataset(
        [staff("Dylan"), staff("Alesa")],
        [],
        requests=[
            request("video", f"REQUEST ALL {both} DO 'video' DURING ANY 1 blocks", MUST),
        ],
    )
    result = run(together)
    assert blocks(result, "video", "dylan") == blocks(result, "video", "alesa")
    assert len(blocks(result, "video", "dylan")) >= 1
    apart = dataset(
        [staff("Dylan"), staff("Alesa")],
        [],
        requests=[
            request("video", f"REQUEST EACH {both} DO 'video' DURING ANY 1 blocks", MUST),
            request("dylan", "REQUEST staff.dylan FREE DURING ALL blocks.all_clinics", MUST),
            request("alesa", "REQUEST staff.alesa FREE DURING blocks.lunch", MUST),
        ],
    )
    result = run(apart)
    assert blocks(result, "video", "dylan") and blocks(result, "video", "alesa")


def test_a_choice_after_a_choice_is_shared():
    members = [staff(n) for n in ("Dylan", "Sarah", "Vic")]
    ds = dataset(
        members,
        [],
        requests=[
            request(
                "two",
                "REQUEST ANY 2 staff DO 'x' DURING ANY 2 blocks.all_clinics",
                MUST,
            ),
            request("none", "REQUEST ALL staff NOT DO 'x'"),
        ],
    )
    result = run(ds)
    doing = [blocks(result, "x", s) for s in ("dylan", "sarah", "vic")]
    doing = [b for b in doing if b]
    assert len(doing) == 2 and doing[0] == doing[1] and len(doing[0]) == 2


def test_a_count_of_activities_counts_different_ones():
    ds = dataset(
        [staff("Rob", archery_1_2=OK, candle_making=OK)],
        [ARCHERY, CANDLE],
        offerings=[
            ("Archery 1 & 2", ["clinic_1"]),
            ("Archery 1 & 2", ["clinic_2"]),
            ("Candle Making", ["clinic_3"]),
        ],
        requests=[
            request(
                "variety",
                "REQUEST staff.rob DO ANY 2 activities.clinics DURING ANY blocks",
                MUST,
            ),
            request("free", "REQUEST staff.rob FREE DURING EACH blocks", Priority.LOW),
        ],
    )
    result = run(ds)
    assert {a.activity for a in result.assignments if a.staff == "rob"} == {
        "archery_1_2",
        "candle_making",
    }


@pytest.mark.parametrize(
    ("bound", "least", "most"), [("AT_LEAST", 120, 150), ("EXACTLY", 120, 120)]
)
def test_a_length_over_a_pool_fills_blocks_but_one(bound, least, most):
    text = f"REQUEST staff.cam DO 'video editing' FOR {bound} 2h DURING ANY blocks.all_clinics"
    ds = dataset(
        [staff("Cam")],
        [],
        requests=[
            request("edit", text, MUST),
            request("free", "REQUEST staff.cam FREE DURING EACH blocks", Priority.LOW),
        ],
    )
    pieces = rows(run(ds), "video editing")
    assert least <= sum(a.minutes for a in pieces) <= most
    assert sum(1 for a in pieces if a.minutes < 75) <= 1  # the blocks are 75 minutes


def test_a_length_in_one_go_is_a_run_of_adjacent_blocks():
    text = (
        "REQUEST staff.cam DO 'video editing' FOR AT_LEAST 2h "
        "DURING ANY CONSECUTIVE {blocks.clinic_1 + blocks.clinic_2 + blocks.clinic_4}"
    )
    ds = dataset([staff("Cam")], [], requests=[request("edit", text, MUST)])
    assert {"clinic_1", "clinic_2"} <= blocks(run(ds), "video editing")


def test_a_length_in_one_piece_is_one_block():
    text = "REQUEST staff.cam DO 'video editing' FOR AT_LEAST 30m DURING ANY 1 blocks"
    ds = dataset(
        [staff("Cam")],
        [],
        requests=[
            request("edit", text, MUST),
            request("free", "REQUEST staff.cam FREE DURING EACH blocks", Priority.LOW),
        ],
    )
    (piece,) = rows(run(ds), "video editing")
    assert piece.minutes >= 30


def test_busy_in_every_block_or_in_one():
    every = "REQUEST staff.hails BUSY DURING ALL {blocks.clinic_4 + blocks.playstation}"
    one = "REQUEST staff.hails BUSY DURING ANY 1 {blocks.clinic_4 + blocks.playstation}"
    work = "REQUEST staff.hails DO 'x' DURING EACH {blocks.clinic_4 + blocks.playstation}"
    free = "REQUEST staff.hails FREE DURING EACH blocks"
    for text, expected in ((every, 2), (one, 1)):
        asked = [
            request("b", text, MUST),
            request("w", work, Priority.LOW),
            request("free", free, Priority.LOW, 2.0),
        ]
        ds = dataset([staff("Hails")], [], requests=asked)
        assert len(rows(run(ds), "x")) == expected


def test_a_statement_with_no_during_is_about_any_block_of_the_day():
    ds = dataset([staff("Dylan")], [], requests=[request("x", "REQUEST staff.dylan DO 'x'", MUST)])
    assert len(rows(run(ds), "x")) >= 1


def test_all_of_a_group_with_a_pool_gives_each_a_block_of_their_own():
    text = "REQUEST ALL {staff.dylan + staff.sarah} DO 'x' DURING ANY blocks.all_clinics"
    ds = dataset(
        [staff("Dylan"), staff("Sarah")],
        [],
        requests=[
            request("x", text, MUST),
            request(
                "dylan",
                "REQUEST staff.dylan FREE DURING EACH {blocks.clinic_1 + blocks.clinic_2}",
                MUST,
            ),
            request(
                "sarah",
                "REQUEST staff.sarah FREE DURING EACH {blocks.clinic_3 + blocks.clinic_4}",
                MUST,
            ),
        ],
    )
    result = run(ds)
    assert blocks(result, "x", "dylan") <= {"clinic_3", "clinic_4"}
    assert blocks(result, "x", "sarah") <= {"clinic_1", "clinic_2"}
    assert blocks(result, "x", "dylan") and blocks(result, "x", "sarah")


def test_a_preference_is_weighed_by_its_outermost_count():
    ds = dataset(
        [staff("Dylan")],
        [],
        requests=[
            request("most", "PREFER staff.dylan DO 'break' DURING AT_MOST 2 blocks"),
            request(
                "four",
                "REQUEST staff.dylan DO 'break' DURING EACH blocks.all_clinics",
                Priority.LOW,
            ),
        ],
    )
    assert len(rows(run(ds), "break")) == 2


def test_a_count_of_blocks_over_pooled_dates_counts_each_block_on_each_date():
    """Yesterday's clinic 1 and today's are two blocks, so two done leaves one of three."""
    yesterday = TARGET - timedelta(days=1)
    window = f"{{{yesterday} .. {TARGET}}}"
    ds = dataset(
        [staff("Dylan")],
        [],
        published=published(
            yesterday, ("Dylan", "'x'", None, "clinic_1"), ("Dylan", "'x'", None, "clinic_2")
        ),
        requests=[
            request(
                "most",
                f"REQUEST staff.dylan DO 'x' DURING AT_MOST 3 blocks ON ANY {window}",
                MUST,
            ),
            request(
                "more", "REQUEST staff.dylan DO 'x' DURING EACH blocks.all_clinics", Priority.LOW
            ),
        ],
    )
    assert len(rows(run(ds), "x", "dylan")) == 1


def test_a_run_of_blocks_over_pooled_dates_stays_within_a_date():
    yesterday = TARGET - timedelta(days=1)
    window = f"{{{yesterday} .. {TARGET}}}"
    ds = dataset(
        [staff("Dylan")],
        [],
        published=published(yesterday, ("Dylan", "'x'", None, "playstation")),
        requests=[
            request(
                "run",
                f"REQUEST staff.dylan DO 'x' DURING AT_MOST 1 CONSECUTIVE blocks ON ANY {window}",
                MUST,
            ),
            request("first", "REQUEST staff.dylan DO 'x' DURING blocks.clinic_1", Priority.LOW),
        ],
    )
    assert blocks(run(ds), "x", "dylan") == {"clinic_1"}  # yesterday's last block is no neighbour


def test_a_group_picks_one_and_not_do_keeps_the_other_out():
    text = (
        "REQUEST ALL {staff.alesa + ANY 1 {staff.dylan + staff.cam}} DO 'video' "
        "DURING ANY 1 blocks.all_clinics"
    )
    members = [staff("Alesa"), staff("Dylan"), staff("Cam")]
    ds = dataset(
        members,
        [],
        requests=[
            request("video", text, MUST),
            request("dylan", "REQUEST staff.dylan DO 'video' DURING blocks.clinic_1", Priority.LOW),
            request("cam", "REQUEST staff.cam DO 'video' DURING blocks.clinic_2", Priority.LOW),
        ],
    )
    filming = {a.staff for a in rows(run(ds), "video")}
    assert {"alesa", "dylan", "cam"} <= filming  # the one not picked is free to film too
    only = replace_text(
        ds,
        "ANY 1 v IN {staff.dylan + staff.cam}\n"
        "REQUEST ALL {staff.alesa + v} DO 'video' DURING ANY 1 blocks.all_clinics\n"
        "REQUEST ALL {{staff.dylan + staff.cam} - v} NOT DO 'video'",
    )
    filming = {a.staff for a in rows(run(only), "video")}
    assert "alesa" in filming and len(filming & {"dylan", "cam"}) == 1


def replace_text(ds, text):
    from dataclasses import replace

    return replace(
        ds, requests=tuple(replace(r, skedge=text) if r.id == "video" else r for r in ds.requests)
    )
