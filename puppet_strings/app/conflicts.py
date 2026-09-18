"""Requests that contradict each other, found without solving. No Qt involved.

The solver will tell you a day is infeasible, but not which two requests disagreed. This
reads the resolved requests instead and looks for the disagreements that are plain on
paper: one person, one date, one block, and two requests asking for things that cannot
both happen.

Only *forced* statements are read — the ones that leave the solver no choice. `REQUEST
staff.rob DO activity.ropes DURING block.clinic_1` claims Rob's clinic 1; `REQUEST
ANY_1_OF staff.all DO …` and `DURING ANY_2_OF block.all` claim nothing in particular,
because the solver picks, and picking around each other is its job, not a conflict. That
keeps this quiet: what it reports is worth looking at.
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
    """Every slot where the requests contradict each other, in calendar order."""
    hard_first = {r.id: r for r in requests}
    slots: dict[tuple[str, date, str], list[Claim]] = {}
    for request in requests:
        for copy in resolved.get(request.id, ()):
            for statement in copy.statements:
                for slot, claim in _claims(statement, request, dataset):
                    slots.setdefault(slot, []).append(claim)
    found = []
    for (staff, day, block), claims in slots.items():
        reasons, involved = _disagreements(claims, dataset.blocks[block].minutes)
        if reasons:
            found.append(Conflict(staff, day, block, tuple(reasons), _order(involved, hard_first)))
    return tuple(sorted(found, key=lambda c: (c.date, c.staff, c.block)))


def _order(ids: set[str], requests: dict[str, Request]) -> tuple[str, ...]:
    """The requests involved, the ones that must happen first: those are the immovable ones."""
    return tuple(sorted(ids, key=lambda i: (not requests[i].priority.hard, i)))


# -- what a statement claims --------------------------------------------------------------


def _claims(statement, request: Request, dataset: Dataset):
    """Every (slot, claim) a statement forces. A statement that leaves a choice forces none."""
    if isinstance(statement, Requirement):
        yield from _requirement_claims(statement, request, dataset)
    elif isinstance(statement, Forbid):
        yield from _forbid_claims(statement, request, dataset)


def _requirement_claims(statement: Requirement, request: Request, dataset: Dataset):
    if not _forced(statement.who) or not _forced(statement.on):
        return
    if statement.during is not None and not _forced(statement.during):
        return
    if statement.what is None:
        claim = Claim(request.id, FREE)
    else:
        target = _one_target(statement.what)
        if target is None:
            return  # the solver picks the activity, so nothing here is settled
        claim = Claim(request.id, DO, target, minutes=statement.minutes)
    during = statement.during.items if statement.during else None
    yield from _slots(statement.who.items, statement.on.items, during, dataset, claim)


def _forbid_claims(statement: Forbid, request: Request, dataset: Dataset):
    pattern = statement.pattern
    if not _forced(statement.who) or not pattern.on.items:
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
    """The claim, once per person, date and block it reaches that the calendar really has."""
    for day in dates:
        if day not in dataset.calendar:
            continue
        on_day = [b.id for b in dataset.blocks_on(day)]
        for block in blocks if blocks is not None else on_day:
            if block not in on_day:
                continue
            for staff_id in staff_ids:
                yield (staff_id, day, block), claim


def _forced(choice: Choice) -> bool:
    """Whether a selector settles the matter: every item, rather than some of them."""
    return choice.kind == ALL and bool(choice.items)


def _one_target(what) -> str | None:
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
    """The reasons the claims on one slot cannot all hold, and the requests making them."""
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
