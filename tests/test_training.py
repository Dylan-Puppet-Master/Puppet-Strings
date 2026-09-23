"""The trainer's problems, and the checker that marks them.

Every problem is held to three things: its answer is valid Skedge that some day of the
session can meet, every alternative it lists is marked right, and every near miss it lists
is marked wrong. That is as much a test of the checker as of the problems.
"""

import random
from datetime import date

import pytest

from puppet_strings.model import Priority
from puppet_strings.training import check
from puppet_strings.training.check import check_answer
from puppet_strings.training.problems import load_levels
from puppet_strings.training.progress import Progress, load_progress
from puppet_strings.training.session import dataset

LEVELS = load_levels()
PROBLEMS = [p for level in LEVELS for p in level.problems]
TUESDAY = date(2026, 8, 4)


def test_there_are_hundreds_of_problems_with_unique_ids():
    assert len(PROBLEMS) >= 200
    ids = [p.id for p in PROBLEMS]
    assert len(ids) == len(set(ids))
    assert all(level.problems for level in LEVELS)


def test_every_problem_is_on_a_day_of_the_session():
    span = dataset(TUESDAY).this_span
    assert all(p.day in span.dates for p in PROBLEMS)


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: p.id)
def test_the_answer_is_valid_and_can_be_met(problem):
    ds = dataset(problem.day)
    copies = check._judged(check._resolve(problem.answer, problem.priority, ds))
    if not copies:
        return  # a score or an exclusion only: nothing for a sample to meet
    universe = check._universe(ds, copies, copies, random.Random(0))
    if not problem.priority.hard:
        # below MUST_HAPPEN a split request is met a copy at a time, and some may not be
        copies = check._meetable(ds, copies, universe, random.Random(0))
    assert copies
    built = check._build(ds, copies, (), universe)
    solver = check._aim(built, universe, random.Random(0), check.AIMS[0])
    assert check._sample(built, solver) is not None


@pytest.mark.parametrize(
    ("problem", "text"),
    [(p, a) for p in PROBLEMS for a in p.alternatives],
    ids=lambda x: getattr(x, "id", ""),
)
def test_every_alternative_is_marked_right(problem, text):
    verdict = check_answer(text, problem.answer, problem.priority, dataset, problem.day)
    assert verdict.correct, f"{verdict.headline}: {verdict.detail}"


@pytest.mark.parametrize(
    ("problem", "text"),
    [(p, w) for p in PROBLEMS for w in p.wrong],
    ids=lambda x: getattr(x, "id", ""),
)
def test_every_near_miss_is_marked_wrong(problem, text):
    verdict = check_answer(text, problem.answer, problem.priority, dataset, problem.day)
    assert not verdict.correct
    assert verdict.error is None, f"a near miss should be valid Skedge: {verdict.detail}"


def test_an_unreadable_answer_says_where():
    verdict = check_answer(
        "REQUEST staff.rob DO 'break' DURING",
        "REQUEST staff.rob FREE DURING blocks.lunch",
        Priority.HIGH,
        dataset,
        TUESDAY,
    )
    assert not verdict.correct and verdict.error is not None and verdict.error.line == 1


def test_a_counterexample_is_a_day_that_tells_them_apart():
    verdict = check_answer(
        "REQUEST staff.rob DO 'break' DURING ANY 1 {blocks.lunch + blocks.dinner}",
        "REQUEST staff.rob DO 'break' DURING blocks.lunch",
        Priority.HIGH,
        dataset,
        TUESDAY,
    )
    assert not verdict.correct and verdict.answer_met is True
    rob = [a for a in verdict.schedule if a.staff == "rob" and a.activity == "break"]
    assert [a.block for a in rob] == ["dinner"]


def test_progress_is_kept_between_runs(tmp_path):
    path = tmp_path / "training.json"
    progress = Progress(path=path)
    progress.of("x").solved = True
    progress.of("x").draft = "REQUEST"
    progress.current = "x"
    progress.save()
    again = load_progress(path)
    assert again.of("x").solved and again.of("x").draft == "REQUEST" and again.current == "x"
    assert load_progress(tmp_path / "missing.json").problems == {}
