"""Take the people an EXCLUDE names out of the days it names.

    EXCLUDE staff.dylan DO 'offsite' DURING ALL_OF blocks.all ON 2026-08-26

Dylan is not at camp that day. Nothing may be assigned to him in those blocks, nothing is
asked of him there, and the schedule says `offsite` where his assignments would have been.

This is the same thing the Adjustments sheet's `resting` does for somebody who is ill, and
it is done the same way: the blocks go into the dataset's resting map, so `Dataset.holds`
is false for them and the solver never makes a variable; a person out for the whole day
drops out of every staff category, so `staff.all` does not offer them and a request written
about a category asks nothing of them. That is what lets the legal breaks keep being
`MUST_HAPPEN` on a day somebody is away: they are asked of the staff who are at camp, and
somebody who is not there is not one of them.

A request naming that person *by name* on a block they are excluded from is a different
matter, and is still wrong: the errors pane says so, and at MUST_HAPPEN the day will not
solve. Saying "Dylan is off today" and "Dylan runs riflery today" is a contradiction, and
no rule here can decide which of them was meant.
"""

from collections import defaultdict
from dataclasses import replace
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import Exclusion
from puppet_strings.skedge.validate import validate_request

KEYWORD = "exclude"  # what a request has to say somewhere before it is worth parsing


def mentions_exclusion(text: str) -> bool:
    """Whether a request could hold an EXCLUDE, cheaply enough to ask of every one."""
    return KEYWORD in text.lower()


def apply_exclusions(dataset: Dataset) -> Dataset:
    """The dataset with every EXCLUDE in its requests applied. Idempotent.

    A request that does not parse is left to the validator to complain about: a broken
    request elsewhere on the sheet is no reason for a day to forget who is away.
    """
    excluded = _gather(dataset)
    if not excluded:
        return dataset
    return _without(dataset, excluded)


def _gather(dataset: Dataset) -> dict[date, dict[str, dict[str, str]]]:
    """Every exclusion there is, as date -> staff -> block -> label."""
    found: dict[date, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for request in dataset.requests:
        for exclusion in _exclusions(request, dataset):
            for day in exclusion.on.items:
                if not isinstance(day, date) or day not in dataset.calendar:
                    continue
                # only the blocks the day actually has: `blocks.all` is the Blocks sheet,
                # and a day it does not run on is not a block anybody could be taken out of
                running = _blocks_on(dataset, day)
                asked = {str(b) for b in exclusion.during.items} if exclusion.during else None
                blocks = [b for b in running if asked is None or b in asked]
                for staff_id in exclusion.who.items:
                    for block in blocks:
                        found[day][str(staff_id)][block] = exclusion.label
    return {day: {s: dict(blocks) for s, blocks in people.items()} for day, people in found.items()}


def _exclusions(request: Request, dataset: Dataset) -> list[Exclusion]:
    """The resolved EXCLUDE statements of one request, or none if it does not hold any."""
    if not mentions_exclusion(request.skedge):
        return []
    try:
        copies = validate_request(request, dataset)
    except SkedgeError:
        return []
    return [st for copy in copies for st in copy.statements if isinstance(st, Exclusion)]


def _blocks_on(dataset: Dataset, day: date) -> tuple[str, ...]:
    """Every block the day has, which is what an EXCLUDE without a DURING means."""
    return tuple(b.id for b in dataset.blocks_on(day))


def _without(dataset: Dataset, excluded: dict[date, dict[str, dict[str, str]]]) -> Dataset:
    """The dataset as the excluded days leave it: resting, categories and staff all follow."""
    resting = {day: dict(people) for day, people in dataset.resting.items()}
    for day, people in excluded.items():
        for staff_id, blocks in people.items():
            was = resting.setdefault(day, {}).get(staff_id, frozenset())
            resting[day][staff_id] = was | frozenset(blocks)
    today = resting.get(dataset.target, {})
    staff = {
        i: replace(member, resting_blocks=member.resting_blocks | today.get(i, frozenset()))
        for i, member in dataset.staff.items()
    }
    # A category never offers somebody who is not working today, which is what keeps a
    # MUST_HAPPEN request written about `staff.all` from asking anything of them.
    all_blocks = frozenset(_blocks_on(dataset, dataset.target))
    working = frozenset(i for i, member in staff.items() if member.resting_blocks != all_blocks)
    categories = {c: members & working for c, members in dataset.staff_categories.items()}
    return replace(
        dataset,
        staff=staff,
        staff_categories=categories,
        resting=resting,
        excluded=excluded,
    )
