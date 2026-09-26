"""Whether an answer to a training problem asks for the same thing as the problem's own.

There is more than one way to write most requests — a category or its members named one by
one, a binding line or an `EACH` in place, `ON dates.target` or no `ON` at all — so an
answer is never compared with the expected text. It is compared by what it does.

1. **Shape.** Both are resolved against the session's data, which is what turns every
   spelling of a set into the same items. If the two resolve to the same statements over the
   same items, they are the same request and that is the end of it.

2. **Behaviour.** Otherwise the solver is asked to find a day that tells them apart: a
   schedule that meets one and not the other. It is built over a small *universe* of what
   might happen that day — the people, tasks and clinics either request mentions, and an
   `'other duties'` task that keeps anybody busy — and sampled many times over with random
   objectives, first the emptiest day each request allows and then days pushed every which
   way. A sample that meets one request is checked against the other with the whole
   schedule held fixed. A sample it does not meet is a counterexample, and the trainee is
   shown it.

   A few things the samples cannot see are checked directly: whether one is a `PREFER` and
   the other a `REQUEST`, what a `PREFER … MAXIMIZE` scores and what an `EXCLUDE` takes out
   of the day, which dates each is about, and — below `MUST_HAPPEN`, where each copy is
   weighed on its own — how many separate requests `EACH` splits each into.

Sampling can miss a difference that only a rare day shows, so "the same" here means that no
day the solver could find told them apart. Every problem's answer and alternatives are run
through this in the test suite, alongside answers that must be told apart.
"""

import os
import random
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date

from ortools.sat.python import cp_model

from puppet_strings.model import Assignment, Dataset, Priority, Request, minute_to_time
from puppet_strings.skedge import ast
from puppet_strings.skedge.resolve import (
    ALL,
    ANY,
    COUNT,
    DEFAULT_POS,
    POOL,
    Choice,
    Exclusion,
    Pattern,
    Requirement,
    Resolved,
    Score,
    Tally,
    is_prefer,
)
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import build_model
from puppet_strings.solver.variables import Literal, Slot, Variables

FILLER = "other duties"  # what the universe keeps somebody busy with, when not asked for more
MOST_DOERS = 12  # people offered the named tasks in a universe, beyond what is asked of them
MOST_ACTIVITIES = 8  # a category of clinics is sampled down to this many
SECONDS = 1.5  # for one sample; any schedule will do, so a good one is plenty
WORKERS = 4  # threads for one sample


@dataclass(frozen=True)
class Verdict:
    """What the checker made of an answer.

    `schedule` is a day that tells the answer from the expected one, when one was found, and
    `answer_met` says which way round: True for a day the answer allows that misses what was
    asked, False for a day that does what was asked and the answer still refuses.
    """

    correct: bool
    headline: str
    detail: str = ""
    error: ast.SkedgeError | None = None
    schedule: tuple[Assignment, ...] = ()
    answer_met: bool | None = None
    day: date | None = None
    staff: tuple[str, ...] = ()  # the people the schedule is about, in the order to show them


def check_answer(
    answer: str,
    expected: str,
    priority: Priority,
    datasets,
    target: date,
    seed: int = 0,
) -> Verdict:
    """Compare an answer with the expected Skedge, both at `priority`.

    `datasets` gives the session's Dataset for a date: `datasets(target)` is the day the
    problem is set on, and any other date either request is about may be asked for too.
    """
    dataset = datasets(target)
    try:
        answer_copies = _resolve(answer, priority, dataset)
    except ast.SkedgeError as e:
        return Verdict(False, "Not valid Skedge", e.message, error=e)
    expected_copies = _resolve(expected, priority, dataset)
    if _canon_copies(answer_copies, dataset) == _canon_copies(expected_copies, dataset):
        return Verdict(True, "Correct")
    dates = _dates(expected_copies)
    shape = _shape_difference(answer_copies, expected_copies, dates, priority, dataset)
    if shape is not None:
        return Verdict(False, "Not quite", shape)
    rng = random.Random(seed)
    for day in _test_dates(dates, target, dataset):
        on_day = datasets(day)
        if day == target:
            both = answer_copies, expected_copies
        else:
            both = _resolve(answer, priority, on_day), _resolve(expected, priority, on_day)
        found = _tell_apart(on_day, *both, priority, rng)
        if found is not None:
            return _counterexample(on_day, *found)
    return Verdict(True, "Correct")


def _resolve(text: str, priority: Priority, dataset: Dataset) -> tuple[Resolved, ...]:
    request = Request(id="answer", description="", skedge=text, priority=priority)
    return validate_request(request, dataset)


# -- shape ---------------------------------------------------------------------------------


def _canon(value, names: dict[str, str], day: tuple[str, ...] = ()):
    """A value with everything that does not change its meaning taken out.

    Positions and the key of a copy go; a variable or a GAP label keeps only the order it was
    first met in, so two requests binding `s` and `who` the same way are the same. A choice of one
    item is that item however it was quantified, and ANY n of n items is all of them.
    A pattern with no DURING is about every block of `day`, which is what it would say if it
    named them all.
    """
    if isinstance(value, Pattern) and value.during is None and day:
        value = replace(value, during=Choice(day, POOL))
    if isinstance(value, Choice):
        items = tuple(sorted(value.items, key=str))
        kind, n, bound = value.kind, value.n, value.bound
        whole = n >= len(items) and not value.consecutive and not value.units
        if whole and (kind == ANY or (kind == COUNT and bound != ast.AT_MOST)):
            kind, bound = ALL, None
        if len(items) == 1 and not value.parts and not value.units:
            kind, n, bound = "one", 1, None
        var = names.setdefault(value.var, f"v{len(names)}") if value.var else None
        parts = _canon(value.parts, names, day)
        units = _canon(value.units, names, day)
        minus = _canon(value.minus, names, day)
        run = value.consecutive and kind in (ANY, COUNT, POOL)
        counted = n if kind in (ANY, COUNT) else None
        return ("choice", items, kind, counted, bound, var, parts, run, units, minus)
    if isinstance(value, ast.Gap):
        amount = (value.amount.bound, value.amount.value, value.amount.duration)
        return ("gap", _label(value.first, names), _label(value.second, names), amount)
    if is_dataclass(value):
        parts = []
        for f in fields(value):
            field = getattr(value, f.name)
            if f.name in ("pos", "key"):
                continue
            if f.name == "label" and not isinstance(value, Exclusion):
                parts.append(_label(field, names))  # an EXCLUDE's is what the schedule says
            else:
                parts.append(_canon(field, names, day))
        return (type(value).__name__, *parts)
    if isinstance(value, frozenset | set):
        return tuple(sorted((_canon(v, names, day) for v in value), key=repr))
    if isinstance(value, dict):
        ordered = sorted(value.items(), key=lambda kv: str(kv[0]))
        return tuple(_canon(v, names, day) for _, v in ordered)
    if isinstance(value, tuple | list):
        return tuple(_canon(v, names, day) for v in value)
    return value


def _label(label: str | None, names: dict[str, str]) -> str | None:
    """A GAP label, known only by the order it was first met in."""
    return names.setdefault(f"label:{label}", f"l{len(names)}") if label else None


def _canon_copies(copies: tuple[Resolved, ...], dataset: Dataset) -> list:
    day = tuple(sorted(b.id for b in dataset.blocks_on(dataset.target)))
    return sorted((_canon(copy, {}, day) for copy in copies), key=repr)


def _statements(copies) -> Iterator:
    for copy in copies:
        yield from copy.statements


def _shape_difference(
    answer, expected, wanted_dates: frozenset[date], priority: Priority, dataset: Dataset
) -> str | None:
    """What the samples cannot see, compared directly. None when nothing differs."""
    kinds = {_kind(st) for st in _statements(answer)}
    wanted = {_kind(st) for st in _statements(expected)}
    if kinds != wanted:
        return _kind_advice(kinds, wanted)
    if _scores(answer) != _scores(expected) or _away(answer, dataset) != _away(expected, dataset):
        return (
            "It is the right kind of statement, but it is about something different. Check "
            "each name in it against the request."
        )
    lengths, wanted_lengths = _lengths(answer), _lengths(expected)
    if lengths != wanted_lengths and _unsorted(lengths) == _unsorted(wanted_lengths):
        return (
            "The lengths are right, but not what they are lengths of. With DURING a FOR is "
            "the length of each piece; with ACROSS it is what the pieces add up to."
        )
    if lengths != wanted_lengths:
        return (
            "The tasks in it last a different length of time. Check each FOR against the "
            "request: a task with no FOR fills its whole block."
        )
    dates = _dates(answer)
    if dates != wanted_dates:
        missing, extra = sorted(wanted_dates - dates), sorted(dates - wanted_dates)
        words = []
        if missing:
            words.append(f"leaves out {_list_dates(missing)}")
        if extra:
            words.append(f"takes in {_list_dates(extra)}")
        return f"It is about different dates: it {' and '.join(words)}."
    if not priority.hard and len(answer) != len(expected):
        return (
            f"It splits into {_copies(len(answer))}, and this one needs "
            f"{_copies(len(expected))}. Below MUST_HAPPEN, each EACH copy is met or missed "
            "on its own, so how a request is split changes what it asks for — look again at "
            "whether each item should count separately (EACH) or all together (ALL)."
        )
    return None


def _lengths(copies) -> set[tuple]:
    """Each quoted task with the FOR length it is asked for with, wherever one is given.

    Last in each is whether the length is of each piece or, with ACROSS, of them all.
    """
    found = set()
    for st in _statements(copies):
        for part in (st, getattr(st, "pattern", None)):
            minutes = getattr(part, "minutes", None)
            if minutes is not None and isinstance(part.what, ast.Task):
                found.add((part.what.text, part.length_bound, minutes, "each"))
        if isinstance(st, Tally) and st.measure is not None:
            what = st.pattern.what
            text = what.text if isinstance(what, ast.Task) else None
            found.add((text, st.measure.bound, st.measure.value, "total"))
    return found


def _unsorted(lengths: set[tuple]) -> set[tuple]:
    """The lengths without whether each is of a piece or a total."""
    return {length[:-1] for length in lengths}


def _kind(statement) -> str:
    if isinstance(statement, Exclusion):
        return "EXCLUDE"
    if isinstance(statement, Score):
        return "PREFER … MAXIMIZE" if statement.maximize else "PREFER … MINIMIZE"
    if is_prefer(statement):
        return "PREFER"
    return "REQUEST"


def _kind_advice(have: set[str], want: set[str]) -> str:
    if "EXCLUDE" in want - have:
        return "Someone is away here, not being asked for something: that is an EXCLUDE."
    if "EXCLUDE" in have - want:
        return "EXCLUDE takes someone out of the day. This one asks for something instead."
    if want - have and all(k.startswith("PREFER") for k in want - have):
        if "REQUEST" in want:
            return (
                "Part of this is a PREFER. The REQUEST lines of a request stand or fall "
                "together; a PREFER is weighed on its own, so missing it costs nothing else."
            )
        return "This one is scored by how close it comes, so it is a PREFER, not a REQUEST."
    if "REQUEST" in want - have:
        return "This one is met or not met, so it is a REQUEST rather than a PREFER."
    return f"This needs {', '.join(sorted(want))}; the answer has {', '.join(sorted(have))}."


def _scores(copies) -> list:
    """Each PREFER … MAXIMIZE or MINIMIZE, as written, however it was spelled."""
    return sorted((_canon(st, {}) for st in _statements(copies) if isinstance(st, Score)), key=repr)


def _away(copies, dataset: Dataset) -> set[tuple]:
    """Who each EXCLUDE takes out of which block on which date, and what it calls it.

    That is all an exclusion means, so however it was split or whether its blocks were
    named, two that come to the same people, blocks and label are the same.
    """
    found = set()
    for st in _statements(copies):
        if not isinstance(st, Exclusion):
            continue
        for day in st.on.items:
            blocks = st.during.items if st.during else [b.id for b in dataset.blocks_on(day)]
            found |= {(who, block, day, st.label) for who in st.who.items for block in blocks}
    return found


def _fixed(statement) -> bool:
    """Statements the samples cannot judge: a score and an exclusion are compared as written."""
    return isinstance(statement, Score | Exclusion)


def _dates(copies) -> frozenset[date]:
    found: set[date] = set()
    for st in _statements(copies):
        found |= set(_on(st))
    for copy in copies:
        for condition in copy.conditions:
            found |= {d for p in _patterns(condition.test) for d in p.on.items}
    return frozenset(found)


def _on(statement) -> tuple:
    if isinstance(statement, Requirement | Exclusion):
        return statement.on.items
    return statement.pattern.on.items


def _patterns(test) -> Iterator[Pattern]:
    if hasattr(test, "parts"):
        for part in test.parts:
            yield from _patterns(part)
    else:
        yield test.tally.pattern


def _list_dates(days: list[date]) -> str:
    shown = [f"{d:%a %b} {d.day}" for d in days[:4]]
    more = f" and {len(days) - 4} more" if len(days) > 4 else ""
    return ", ".join(shown) + more


def _copies(n: int) -> str:
    return "one request" if n == 1 else f"{n} separate requests"


def _test_dates(dates: frozenset[date], target: date, dataset: Dataset) -> list[date]:
    """The problem's own day, and the last other day the request is about, if it has one.

    The last day matters because a request that may still be met later is only forced on
    the last day it can be met, and that is where a "some day" and a "that day" part.
    """
    days = [target]
    later = sorted(d for d in dates if d != target and d in dataset.calendar)
    if later:
        days.append(later[-1])
    return days


# -- behaviour -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Sample:
    """A schedule, as the value of every assignment variable and each movable task's length."""

    on: frozenset[Slot]
    sizes: dict[Slot, int]
    starts: dict[Slot, int]


def _tell_apart(dataset: Dataset, answer, expected, priority: Priority, rng: random.Random):
    """A sample that meets one and not the other, and which one it meets; or None."""
    answer, expected = _judged(answer), _judged(expected)
    universe = _universe(dataset, answer, expected, rng)
    if not priority.hard:
        answer = _meetable(dataset, answer, universe, rng)
        expected = _meetable(dataset, expected, universe, rng)
    # One model requiring each side, with the other free: samples of the expected request
    # are checked against the answer's model, and the other way round. Each is built once;
    # a sample only changes what it aims for. The two take turns, so that a difference the
    # fullest day shows in the second is found before the first has run through its aims.
    # The two samples of one aim are separate models, so on a computer with the cores for
    # both they are solved side by side; they are aimed, and then judged, in the same order
    # as if they took turns. With fewer cores they do take turns: a sample has a fixed time,
    # and sharing the cores would leave each one weaker, which is a wrong answer passed.
    requiring = {
        False: _build(dataset, expected, answer, universe),
        True: _build(dataset, answer, expected, universe),
    }
    live = [False, True]  # whether the day being sampled is one the answer meets
    side_by_side = _cores() >= 2 * WORKERS
    with ThreadPoolExecutor(max_workers=len(live) if side_by_side else 1) as pool:
        for aim in AIMS:
            aimed = [(side, _aim(requiring[side], universe, rng, aim)) for side in live]
            samples = pool.map(lambda job: _sample(requiring[job[0]], job[1]), aimed)
            for (answer_met, _), sample in zip(aimed, list(samples), strict=True):
                if sample is None:
                    live.remove(answer_met)  # nothing meets that side today
                elif not _meets(requiring[not answer_met], sample):
                    return sample, answer_met, universe
    return None


def _meetable(dataset: Dataset, copies, universe, rng) -> tuple[Resolved, ...]:
    """The copies, or when they cannot all be met today, as many as can be met together.

    Below MUST_HAPPEN a request split with EACH is met a copy at a time, and one copy
    nobody can staff — a cabin act asking for a skill nobody here has — leaves the rest
    still worth meeting. Held all at once, it would make every day look the same.
    """
    if len(copies) < 2:
        return copies
    built = _build(dataset, (), copies, universe)
    live = [sat for sat in built.soft.values() if not isinstance(sat, bool)]
    built.model.Maximize(sum(live))
    solver = _solver(rng)
    status = solver.Solve(built.model)
    if status == cp_model.INFEASIBLE:
        return ()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return copies  # out of time: judge them as they are rather than not at all
    return tuple(
        copy
        for i, copy in enumerate(copies)
        if (sat := built.soft.get(i, True)) is True or (sat is not False and solver.Value(sat))
    )


def _judged(copies: tuple[Resolved, ...]) -> tuple[Resolved, ...]:
    """The copies with what the samples judge in them, a `PREFER` count read as a `REQUEST`.

    A preference is weighed rather than met, but what it counts is a pattern like any other,
    and a pattern is what the samples can tell apart; the scores and the exclusions were
    compared as written.
    """
    judged = []
    for copy in copies:
        copy = copy.keeping(lambda st: not _fixed(st))
        statements = tuple(
            replace(st, prefer=False) if isinstance(st, Tally) else st for st in copy.statements
        )
        if statements:
            judged.append(replace(copy, statements=statements))
    return tuple(judged)


@dataclass(frozen=True)
class _Universe:
    """What may happen on the day being sampled, as copies asking for it at a soft priority."""

    copies: tuple[Resolved, ...]
    staff: tuple[str, ...]
    differing: frozenset[str]  # the people, blocks, clinics and tasks only one side names


def _universe(dataset: Dataset, answer, expected, rng: random.Random) -> _Universe:
    """The people, tasks and clinics either request is about, each free to happen or not.

    People in one request's sets and not the other's are what tell two sets apart, so they
    come first. Everybody either names is in it, since a request about a whole category
    can only be met if every one of them can be given something to do.
    """
    mine, theirs = _mentions(dataset, answer), _mentions(dataset, expected)
    kinds = ("staff", "activities", "tasks", "blocks")
    differing = frozenset().union(*(mine[k] ^ theirs[k] for k in kinds))
    staff = sorted(mine["staff"] | theirs["staff"])
    # Anybody may be kept busy, but only some are offered the tasks the requests name: the
    # people that tell the two apart, and enough of the rest to see how they are treated.
    doers = _pick(mine["staff"], theirs["staff"], MOST_DOERS, rng)
    activities = _pick(mine["activities"], theirs["activities"], MOST_ACTIVITIES, rng)
    tasks = sorted(mine["tasks"] | theirs["tasks"] | {FILLER})
    target = dataset.target
    blocks = _blocks(dataset, mine, theirs)
    # Clinics run in the blocks the day offers clinics in, and anywhere a request puts one by
    # name. A pool or a count of clinics puts none anywhere: it counts the ones that run.
    offered = {b for o in dataset.offerings for b in o.blocks} | mine["placed"] | theirs["placed"]
    runs = [b for b in blocks if b in offered]
    on = Choice((target,), ALL)
    copies = []
    for s in staff:
        for task in tasks if s in doers else [FILLER]:
            for b in blocks:
                copies.append(_asking(Choice((s,), ALL), ast.Task(task), Choice((b,), ALL), on))
    everyone = tuple(sorted(dataset.staff_categories.get("all", frozenset())))
    anyone = Choice(everyone, ANY, 1)
    for a in activities:
        for b in runs:
            copies.append(_asking(anyone, Choice((a,), ALL), Choice((b,), ALL), on))
    return _Universe(tuple(copies), tuple(staff), differing)


def _blocks(dataset: Dataset, mine: dict, theirs: dict) -> list[str]:
    """The blocks worth sampling: every block both requests could be about, and no more.

    A request that names its blocks is about those and whatever overlaps them, since being
    free in a block means nothing overlapping it. One that leaves a pattern's DURING out is
    about the whole day, and so is the universe.
    """
    today = dataset.blocks_on(dataset.target)
    named = mine["blocks"] | theirs["blocks"]
    if mine["whole_day"] or theirs["whole_day"] or not named:
        return [b.id for b in today]
    return [
        b.id for b in today if b.id in named or any(b.overlaps(dataset.blocks[n]) for n in named)
    ]


def _asking(who: Choice, what, during: Choice, on: Choice) -> Resolved:
    requirement = Requirement(
        who=who,
        what=what,
        during=during,
        on=on,
        role=None,
        minutes=None,
        with_=None,
        without=None,
        label=None,
        pos=DEFAULT_POS,
    )
    return Resolved(key="", bindings={}, statements=(requirement,), gaps=(), when=((),))


def _mentions(dataset: Dataset, copies) -> dict[str, set]:
    """Every person, activity and quoted task anywhere in some copies."""
    found: dict = {"staff": set(), "activities": set(), "tasks": set(), "blocks": set()}
    found["whole_day"] = False
    found["placed"] = set()  # the blocks a statement puts a clinic in by name
    today = {b.id for b in dataset.blocks_on(dataset.target)}

    def walk(value) -> None:
        if isinstance(value, ast.Task):
            found["tasks"].add(value.text)
        elif isinstance(value, Choice):
            for item in value.items:
                if item in dataset.staff:
                    found["staff"].add(item)
                elif item in dataset.activities:
                    found["activities"].add(item)
                elif item in dataset.blocks:
                    found["blocks"].add(item)
            walk(value.parts)
            walk(value.units)
        elif is_dataclass(value):
            if isinstance(value, Requirement | Tally):
                _placed(value, found["placed"], today)
            # a pattern over every block of the day, `DURING ANY CONSECUTIVE blocks`, is
            # about the whole day as much as one with no DURING, and names no block in it
            whole = isinstance(value, Pattern) and (
                value.during is None or today <= set(value.during.items)
            )
            found["whole_day"] |= whole
            for f in fields(value):
                if not (whole and f.name == "during"):
                    walk(getattr(value, f.name))
        elif isinstance(value, frozenset | set | tuple | list):
            for v in value:
                if isinstance(v, str) and v in dataset.staff:
                    found["staff"].add(v)
                else:
                    walk(v)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)

    walk(copies)
    # somebody resting all day can be given nothing, so they tell nothing apart
    found["staff"] = {s for s in found["staff"] if not today <= dataset.staff[s].resting_blocks}
    return found


def _placed(statement, placed: set, today: set) -> None:
    """The blocks a statement names a clinic in, which it may make run there."""
    part = statement if isinstance(statement, Requirement) else statement.pattern
    what = part.what
    if isinstance(what, Choice) and what.kind == ALL:
        placed |= set(part.during.items) if part.during else today


def _pick(mine: set, theirs: set, most: int, rng: random.Random) -> list:
    """Up to `most` items: first the ones only one side has, then the ones both have."""
    differing = sorted(mine ^ theirs)
    shared = sorted(mine & theirs)
    rng.shuffle(differing)
    rng.shuffle(shared)
    half = max(most // 2, most - len(shared))
    chosen = differing[:half]
    chosen += shared[: most - len(chosen)]
    chosen += differing[half:][: most - len(chosen)]
    return sorted(chosen)


@dataclass(frozen=True)
class _Built:
    """A model with its variables, and the literal each soft copy is met by, by position."""

    model: cp_model.CpModel
    variables: Variables
    soft: dict[int, Literal]


def _build(dataset: Dataset, hard, soft, universe: _Universe) -> _Built:
    """The solver's own model with `hard` required, and `soft` and the universe free."""
    must = Request("hard", "", "", Priority.MUST_HAPPEN)
    around = Request("universe", "", "", Priority.LOW)
    maybe = [Request(f"soft {i}", "", "", Priority.LOW) for i in range(len(soft))]
    copies = (
        [(must, c) for c in hard]
        + list(zip(maybe, soft, strict=True))
        + [(around, c) for c in universe.copies]
    )
    model, variables, compiler, _ = build_model(dataset, copies)
    position = {id(request): i for i, request in enumerate(maybe)}
    met = {position[id(c.request)]: c.sat for c in compiler.compiled if id(c.request) in position}
    return _Built(model, variables, met)


# What each sample aims for, in turn: the emptiest day, choosing what only one side names
# where there is a choice, then choosing anything else; the fullest day; and random ones.
# A near miss usually differs in one name, and the emptiest day that picks that name is
# the day that shows it.
AIMS = ("fewest+", "fewest-", "most", "random+", "fewest+", "random", "fewest-", "random+")


def _aim(built: _Built, universe: _Universe, rng, aim: str) -> cp_model.CpSolver:
    """Point the model at what `aim` says, and give back the solver to sample it with."""
    weights = {}
    for slot, var in built.variables.x.items():
        differs = {slot.staff, slot.activity, slot.block} & universe.differing
        if aim == "most":
            weight = 10 + rng.random()
        elif aim.startswith("random"):
            weight = rng.uniform(-10, 10) + (16 if aim == "random+" and differs else 0)
        else:
            weight = -10 - 2 * rng.random()
            if differs:
                # worth doing for its own sake, or worth even less than anything else
                weight += 16 if aim == "fewest+" else -6
        if slot.activity == FILLER:
            weight -= 3  # what the requests are about comes before keeping somebody busy
        if slot.staff not in universe.staff:
            # somebody neither request is about, only there to fill a position: kept out of
            # an empty day, and cheap enough on a full one not to stop a clinic running
            weight = -1 if aim == "most" or aim.startswith("random") else -30
        weights.setdefault(var.Index(), (weight, var))
    built.model.ClearObjective()
    built.model.Maximize(sum(round(100 * w) * var for w, var in weights.values()))
    return _solver(rng)


def _sample(built: _Built, solver: cp_model.CpSolver) -> _Sample | None:
    """A schedule meeting what the model requires, as it was aimed; None if there is none."""
    if solver.Solve(built.model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    on = frozenset(slot for slot, var in built.variables.x.items() if solver.Value(var))
    sizes, starts = {}, {}
    for slot in on:
        interval = built.variables.intervals[slot]
        if interval.partial:
            sizes[slot] = solver.Value(interval.size)
            starts[slot] = solver.Value(interval.start)
    return _Sample(on, sizes, starts)


def _meets(built: _Built, sample: _Sample) -> bool:
    """Whether what the model requires holds on the sample, every assignment held to it."""
    x = built.variables.x
    if not sample.on <= x.keys():
        return False  # the sample holds something this model cannot, which it does not allow
    model = built.model.Clone()  # the fixed assignments are for this sample alone
    model.ClearObjective()
    same = model.GetIntVarFromProtoIndex
    for slot, var in x.items():
        model.Add(same(var.Index()) == (1 if slot in sample.on else 0))
    for slot, size in sample.sizes.items():
        model.Add(same(built.variables.intervals[slot].size.Index()) == size)
    return _solver(random.Random(0)).Solve(model) != cp_model.INFEASIBLE


def _cores() -> int:
    """The cores this process may run on, which a container or a CI runner may limit."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not on every system
        return os.cpu_count() or 1


def _solver(rng: random.Random) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SECONDS
    solver.parameters.num_workers = WORKERS
    solver.parameters.random_seed = rng.randrange(1 << 16)
    return solver


def _counterexample(dataset: Dataset, sample: _Sample, answer_met: bool, universe: _Universe):
    blocks = dataset.blocks
    schedule = []
    for slot in sorted(sample.on, key=lambda s: (s.staff, blocks[s.block].start_minute)):
        block = blocks[slot.block]
        start = sample.starts.get(slot, block.start_minute)
        schedule.append(
            Assignment(
                staff=slot.staff,
                activity=slot.activity,
                role=slot.role,
                date=dataset.target,
                block=slot.block,
                start=minute_to_time(start),
                minutes=sample.sizes.get(slot, block.minutes),
            )
        )
    detail = (
        "This day meets your request but not the one asked for."
        if answer_met
        else "This day meets the request asked for, but not yours."
    )
    people = sorted({a.staff for a in schedule} | set(universe.staff))
    return Verdict(
        False,
        "Not quite",
        detail,
        schedule=tuple(schedule),
        answer_met=answer_met,
        day=dataset.target,
        staff=tuple(people),
    )
