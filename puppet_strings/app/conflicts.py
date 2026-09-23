"""Requests that contradict each other, found without solving. No Qt involved.

The solver will tell you a day is infeasible, but not which two requests disagreed. This
reads the resolved requests instead and looks for the disagreements that are plain on
paper: one person, one date, one block, and two requests asking for things that cannot
both happen.

A conflict is a day that cannot be scheduled at all, which is a narrower thing than two
requests wanting different things of the same person. Two conditions hold before one is
reported, and both of them are what keeps this quiet enough to be worth reading:

*   Every request involved is MUST_HAPPEN. Anything softer is weighed rather than
    promised: the solver drops the lower priority one and the day still comes out, with
    the report saying what went unfulfilled. Only what must happen can make a day
    impossible, so only what must happen is read here.
*   The statements are *forced* — they leave the solver no choice. `REQUEST staff.rob DO
    activities.clinics.ropes DURING blocks.clinic_1` claims Rob's clinic 1; `REQUEST
    ANY 1 staff.all DO …` and `DURING ANY 2 blocks.all` claim nothing in particular,
    because the solver picks, and picking around each other is its job.

Two MUST_HAPPEN requests meeting in one slot are not a conflict by themselves: two asking
for the same clinic agree, and two half-hour tasks share a block quite happily. What they
say about the slot has to be impossible, which is what `_disagreements` looks for.
"""

from dataclasses import dataclass
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.resolve import ALL, Choice, Forbid, Requirement, Resolved

DO = "do"  # this person does this one thing here
FREE = "free"  # this person does nothing here
NOT_DO = "not do"  # this person does not do these things here
BUSY = "busy"  # this person does something here, whatever it is


@dataclass(frozen=True)
class Claim:
    """What one request says about one person, in one block, on one date."""

    request: str
    kind: str
    target: str | None = None  # DO: the one activity or quoted task
    forbidden: frozenset[str] = frozenset()  # NOT_DO: everything it rules out
    minutes: int | None = None  # how much of the block a DO takes; None is all of it

    def fills(self, block_minutes: int) -> int:
        """The minutes of the block this claim takes up."""
        return block_minutes if self.minutes is None else self.minutes


@dataclass(frozen=True)
class Conflict:
    """Two or more requests that cannot all be met, and where they collide."""

    staff: str
    date: date
    block: str
    reasons: tuple[str, ...]
    requests: tuple[str, ...]

    @property
    def where(self) -> str:
        """The slot, for a heading."""
        return f"{self.staff} · {self.date:%a %Y-%m-%d} · {self.block}"


def find_conflicts(
    requests: list[Request], resolved: dict[str, tuple[Resolved, ...]], dataset: Dataset
) -> tuple[Conflict, ...]:
    """Every slot where the requests contradict each other, in calendar order.

    Only MUST_HAPPEN requests are read, so a slot a preference and a promise both reach is
    not a slot anything can go wrong in: the solver keeps the promise and weighs the
    preference, which is the whole of what the priorities are for.
    """
    must_happen = [r for r in requests if r.priority.hard]
    slots: dict[tuple[str, date, str], list[Claim]] = {}
    for request in must_happen:
        for copy in resolved.get(request.id, ()):
            for statement in copy.statements:
                for slot, claim in _claims(statement, request, dataset):
                    slots.setdefault(slot, []).append(claim)
    found = []
    for (staff, day, block), claims in slots.items():
        reasons, involved = _disagreements(claims, dataset.blocks[block].minutes)
        if reasons:
            found.append(Conflict(staff, day, block, tuple(reasons), tuple(sorted(involved))))
    return tuple(sorted(found, key=lambda c: (c.date, c.staff, c.block)))


# -- what a statement claims --------------------------------------------------------------


def _claims(statement, request: Request, dataset: Dataset):
    """Every (slot, claim) a statement forces. A statement that leaves a choice forces none."""
    if isinstance(statement, Requirement):
        yield from _requirement_claims(statement, request, dataset)
    elif isinstance(statement, Forbid):
        yield from _forbid_claims(statement, request, dataset)


def _requirement_claims(statement: Requirement, request: Request, dataset: Dataset):
    if not forced(statement.who) or not forced(statement.on):
        return
    if statement.during is not None and not forced(statement.during):
        return
    if statement.what is None:
        claim = Claim(request.id, FREE)
    else:
        target = one_target(statement.what)
        if target is None:
            return  # the solver picks the activity, so nothing here is settled
        claim = Claim(request.id, DO, target, minutes=statement.minutes)
    during = statement.during.items if statement.during else None
    yield from _slots(statement.who.items, statement.on.items, during, dataset, claim)


def _forbid_claims(statement: Forbid, request: Request, dataset: Dataset):
    pattern = statement.pattern
    if not forced(statement.who) or not pattern.on.items:
        return
    if pattern.busy:  # REQUEST … NOT FREE: something must happen here
        claim = Claim(request.id, BUSY)
    else:
        forbidden = _targets(pattern.what)
        if not forbidden:
            return
        claim = Claim(request.id, NOT_DO, forbidden=forbidden)
    during = pattern.during.items if pattern.during else None
    yield from _slots(statement.who.items, pattern.on.items, during, dataset, claim)


def _slots(staff_ids, dates, blocks, dataset: Dataset, claim: Claim):
    """The claim, once per slot it reaches that could hold an assignment at all.

    `Dataset.holds` is the same question the solver asks before it makes a variable, so a
    slot nothing can be put in — the block is not on that day, or the person is resting
    through it — is not a slot two requests can disagree over.
    """
    for day in dates:
        if day not in dataset.calendar:
            continue
        for block in blocks if blocks is not None else [b.id for b in dataset.blocks_on(day)]:
            for staff_id in staff_ids:
                if dataset.holds(staff_id, day, block):
                    yield (staff_id, day, block), claim


def forced(choice: Choice) -> bool:
    """Whether a selector settles the matter: every item, rather than some of them.

    The errors pane asks the same question of the same statements, so it is one answer
    here rather than two that could come to differ.
    """
    return choice.kind == ALL and bool(choice.items)


def one_target(what) -> str | None:
    """The single activity or quoted task a requirement names, if it names one."""
    if isinstance(what, ast.Task):
        return what.text
    if isinstance(what, Choice) and what.kind == ALL and len(what.items) == 1:
        return str(what.items[0])
    return None


def _targets(what) -> frozenset[str]:
    """Everything a `NOT DO` rules out."""
    if isinstance(what, ast.Task):
        return frozenset({what.text})
    if isinstance(what, Choice):
        return frozenset(str(item) for item in what.items)
    return frozenset()


# -- what disagrees -----------------------------------------------------------------------


def _disagreements(claims: list[Claim], block_minutes: int) -> tuple[list[str], set[str]]:
    """The reasons the claims on one slot cannot all hold, and the requests making them.

    Every claim here is one a MUST_HAPPEN request makes. Sharing a slot is not the
    disagreement — a slot holds as many promises as fit in it — so what is looked for is
    the pairs that cannot both be kept.
    """
    reasons: list[str] = []
    involved: set[str] = set()

    def clash(reason: str, *making: Claim) -> None:
        reasons.append(reason)
        involved.update(claim.request for claim in making)

    doing = _first_of(claims, DO)
    free = _first_of(claims, FREE)
    busy = _first_of(claims, BUSY)

    for free_claim in free:
        for do_claim in doing:
            clash(f"must be free, and is asked to do {do_claim.target}", free_claim, do_claim)
        for busy_claim in busy:
            clash("must be free, and must not be free", free_claim, busy_claim)
    for do_claim in doing:
        for forbidding in _first_of(claims, NOT_DO):
            if do_claim.target in forbidding.forbidden:
                clash(f"must do {do_claim.target}, and must not do it", do_claim, forbidding)
    for first, second in _pairs(_by_target(doing)):
        together = first.fills(block_minutes) + second.fills(block_minutes)
        if together > block_minutes:
            clash(
                f"must do {first.target} and {second.target} at once, "
                f"which needs {together} minutes of a {block_minutes}-minute block",
                first,
                second,
            )
    return reasons, involved


def _first_of(claims: list[Claim], kind: str) -> list[Claim]:
    """One claim per request of this kind: a request repeating itself is not a conflict."""
    seen: dict[Claim, None] = {}
    for claim in claims:
        if claim.kind == kind:
            seen.setdefault(claim, None)
    return list(seen)


def _by_target(doing: list[Claim]) -> list[Claim]:
    """One claim per thing being done: two requests asking for the same thing agree."""
    seen: dict[str | None, Claim] = {}
    for claim in doing:
        kept = seen.get(claim.target)
        if kept is None or _room(claim) > _room(kept):
            seen[claim.target] = claim
    return list(seen.values())


def _room(claim: Claim) -> tuple[bool, int]:
    """How much of a block a claim wants; one on the whole block outranks any part of it."""
    return claim.minutes is None, claim.minutes or 0


def _pairs(claims: list[Claim]):
    """Every pair, the two from one request included: a request can contradict itself."""
    for i, first in enumerate(claims):
        yield from ((first, second) for second in claims[i + 1 :])


def summary(conflicts: tuple[Conflict, ...]) -> str:
    """A line for the window: how much disagrees, and about whom."""
    if not conflicts:
        return "No conflicts"
    people = len({c.staff for c in conflicts})
    return f"{len(conflicts)} conflict(s) over {people} staff member(s)"
