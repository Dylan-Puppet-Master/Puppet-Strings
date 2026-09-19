"""Turn the cabin act sheets into requests on the Requests sheet.

The cabin act block is a time when campers may do anything, and someone other than the
Puppet Master fills in what each cabin is doing and who they want along: a named person, a
staff category, or anyone with a skill. Each cabin act becomes one CLINIC request holding
one statement per hero asked for, tagged GENERATED_TAG and CABIN_ACT_TAG, so the Puppet
Master can see, edit or delete it before solving.

The hero asked for decides how the task reads. A named person is being asked for as
themselves, so the task is `help P4 with CA`; anyone else is being asked for what they can
do, so it is `LIFEGUARD with P4`. Two staff asked for are two statements and therefore two
people, which is what `ANY_1_OF` per statement buys over one statement asking for two.

Importing again first removes every cabin act request there is, not just the target date's,
because one import reads every sheet in the folder and so speaks for the whole season.
"""

from collections.abc import Mapping
from datetime import date

from puppet_strings.generate import GENERATED_TAG
from puppet_strings.model import Dataset, Priority, Request
from puppet_strings.names import normalize
from puppet_strings.sheets.cabin_acts import WEEKDAYS, CabinAct, parse_title
from puppet_strings.sheets.skills import SKILLS_PREFIX
from puppet_strings.sheets.source import LoadError

CABIN_ACT_TAG = "cabin act"
CABIN_ACT_BLOCK = "cabin_act"  # the Blocks sheet's own name for the slot
ID_PREFIX = "cabin_act:"


def cabin_act_requests(
    boards: Mapping[str, tuple[CabinAct, ...]], dataset: Dataset
) -> tuple[list[Request], list[str]]:
    """One CLINIC request per cabin act across every sheet, plus warnings.

    `boards` maps each sheet's title, which says the session and week, to its Board tab's
    acts. Anything that cannot be placed or named is a warning rather than an error: a
    typo in one cabin's HEROES cell should not cost the other hundred acts their requests.
    """
    if CABIN_ACT_BLOCK not in dataset.blocks:
        raise LoadError(
            f"Blocks: no '{CABIN_ACT_BLOCK}' block, so there is no cabin act slot to schedule in"
        )
    requests: list[Request] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}  # request id -> the sheet that already made it
    for title in sorted(boards):
        session, week = parse_title(title, title)
        dates = _week_dates(dataset, session, week)
        if dates is None:
            warnings.append(f"{title}: the Calendar sheet has no session {session} week {week}")
            continue
        for act in boards[title]:
            request, act_warnings = _request(act, dates, title, dataset)
            warnings += act_warnings
            if request is None:
                continue
            if request.id in seen:
                warnings.append(
                    f"{title}: {act.cabin} on {act.weekday} is already on {seen[request.id]}"
                )
                continue
            seen[request.id] = title
            requests.append(request)
    return requests, warnings


def _week_dates(dataset: Dataset, session: int, week: int) -> dict[str, date] | None:
    """That week's dates by lowercase weekday name, or None if the Calendar has no such week."""
    if session not in dataset.sessions:
        return None
    dates = dataset.weeks(session).get(week)
    if not dates:
        return None
    return {WEEKDAYS[d.weekday()]: d for d in dates if d.weekday() < len(WEEKDAYS)}


def _request(
    act: CabinAct, dates: dict[str, date], title: str, dataset: Dataset
) -> tuple[Request | None, list[str]]:
    """One cabin act's request, or None with the reason it could not be made."""
    day = dates.get(act.weekday)
    if day is None:
        return None, [
            f"{title}: {act.cabin} is on a {act.weekday} the Calendar sheet has no day for"
        ]
    statements, warnings = [], []
    for hero in act.heroes:
        who, task = _hero(hero, act.cabin, dataset)
        if who is None:
            warnings.append(
                f"{title}: {act.cabin} on {act.weekday} asks for '{hero}', who is no staff "
                "member, staff category or skill"
            )
            continue
        statements.append(
            f"REQUEST {who} DO '{task}' DURING blocks.{CABIN_ACT_BLOCK} ON {day.isoformat()}"
        )
    if not statements:
        return None, warnings
    described = f"{act.cabin} cabin act"
    return (
        Request(
            id=f"{ID_PREFIX}{day.isoformat()}:{normalize(act.cabin)}",
            description=f"{described}: {act.activity}" if act.activity else described,
            skedge="\n".join(statements),
            priority=Priority.CLINIC,
            tags=(GENERATED_TAG, CABIN_ACT_TAG),
            created=day,
        ),
        warnings,
    )


def _hero(hero: str, cabin: str, dataset: Dataset) -> tuple[str | None, str]:
    """Who a HEROES entry asks for, and the ad hoc task that says what they are there for."""
    name = normalize(hero)
    if name in dataset.staff:
        return f"staff.{name}", _task(f"help {cabin} with CA")
    for category in (name, f"{SKILLS_PREFIX}{name}"):
        if category in dataset.staff_categories:
            return f"ANY_1_OF staff.{category}", _task(f"{hero} with {cabin}")
    return None, ""


def _task(text: str) -> str:
    """An ad hoc task's text, which Skedge quotes with `'` and so cannot itself contain one."""
    return text.replace("'", "")


def is_cabin_act(request: Request) -> bool:
    """Whether a request was made by importing the cabin act sheets."""
    return CABIN_ACT_TAG in request.tags


def merge(existing: list[Request], generated: list[Request]) -> list[Request]:
    """Every request that is not a cabin act, plus the ones just imported.

    Unlike the offerings, this drops cabin act requests for every date: an import reads
    every sheet in the folder, so what it produces is the whole truth about cabin acts.
    """
    return [r for r in existing if not is_cabin_act(r)] + list(generated)
