"""Requests that ask for something that cannot happen, found without solving. No Qt.

A conflict (`app.conflicts`) is two requests that disagree. This is the other half of the
errors pane: one request, on its own, asking for something the sheets say is impossible.

    REQUEST staff.henry DO activities.aerial_silks DURING blocks.clinic_3 ON 2026-06-19

is a perfectly good sentence, and the validator passes it: every name in it exists. It is
still wrong twice over if Henry is not checked off on aerial silks, and if aerial silks is
not offered in clinic 3 that day. The solver would say only that the request could not be
met, and only once the day had been solved. Both are plain on the sheets, so both are said
here, while the request is still on the screen that made it.

Like the conflict finder, this reads only what is *settled*. `ANY_1_OF staff.all` names
nobody in particular, so nobody in particular is unqualified: the solver picks somebody who
is checked off, and that is its job.
"""

from dataclasses import dataclass
from datetime import date

from puppet_strings.app.conflicts import forced, one_target
from puppet_strings.generate import is_generated
from puppet_strings.model import (
    ANY_SKILL,
    TRAINEE_ROLES,
    Activity,
    Dataset,
    Position,
    Request,
    Staff,
)
from puppet_strings.skedge.resolve import TRAINEE, Requirement, Resolved

TRAINING = TRAINEE_ROLES + (TRAINEE,)  # shadow, scaffolded, and the trainee that becomes one


@dataclass(frozen=True)
class Problem:
    """One request asking for something that cannot be, and where it asks for it."""

    request: str
    message: str
    day: date | None = None
    staff: str | None = None
    block: str | None = None

    @property
    def where(self) -> str:
        """The slot it is about, for a heading; as much of one as the request names."""
        parts = [p for p in (self.staff, _written(self.day), self.block) if p]
        return " · ".join(parts) or self.request


def _written(day: date | None) -> str:
    return f"{day:%a %Y-%m-%d}" if day else ""


def find_errors(
    requests: list[Request], resolved: dict[str, tuple[Resolved, ...]], dataset: Dataset
) -> tuple[Problem, ...]:
    """Every request that asks for something the sheets rule out, in calendar order."""
    found: list[Problem] = []
    offered = _offered(dataset)
    for request in requests:
        if is_generated(request, dataset.target):
            continue  # the offerings are what the day offers; they cannot disagree with it
        for copy in resolved.get(request.id, ()):
            for statement in copy.statements:
                if isinstance(statement, Requirement):
                    found += _of_requirement(statement, request, dataset, offered)
    return tuple(_distinct(found))


def _distinct(found: list[Problem]) -> list[Problem]:
    """Each problem once, in date order. `EACH_OF` makes the same copy again and again."""
    seen = dict.fromkeys(found)
    return sorted(seen, key=lambda p: (p.day or date.min, p.staff or "", p.request))


def _of_requirement(statement: Requirement, request: Request, dataset: Dataset, offered) -> list:
    """What one `REQUEST … DO …` asks for that cannot be."""
    activity_id = one_target(statement.what)
    if activity_id is None or activity_id not in dataset.activities:
        return []  # FREE, a quoted task, or an activity the solver is left to pick
    activity = dataset.activities[activity_id]
    found = _unqualified(statement, request, dataset, activity)
    return found + _unoffered(statement, request, dataset, activity, offered)


# -- who may do it --------------------------------------------------------------------------


def _unqualified(statement: Requirement, request: Request, dataset: Dataset, activity) -> list:
    """The named people who could not hold the position they are being asked to hold."""
    if not forced(statement.who):
        return []  # the solver picks somebody who can, which is what a quantifier is for
    role = _named_role(statement)
    if role in TRAINING:
        return []  # a trainee is somebody not checked off yet; that is what training is
    found = []
    for staff_id in statement.who.items:
        member = dataset.staff.get(str(staff_id))
        if member is None:
            continue
        why = _refused(member, activity, role)
        if why:
            found.append(Problem(request.id, why, staff=str(staff_id)))
    return found


def _named_role(statement: Requirement) -> str | None:
    """The one role the request asks for, if it asks for one."""
    if statement.role is None or len(statement.role.items) != 1:
        return None
    return str(statement.role.items[0])


def _refused(member: Staff, activity: Activity, role: str | None) -> str:
    """Why this person cannot hold this position, or "" if they can."""
    positions = activity.positions if role is None else [activity.position(role)]
    positions = [p for p in positions if p is not None]
    if not positions:
        return f"{activity.name} has no {role} position"
    if any(p.allows(member) for p in positions):
        return ""
    where = f"the {role} position on {activity.name}" if role else activity.name
    return f"{member.name} cannot hold {where}: {_because(member, positions)}"


def _because(member: Staff, positions: list[Position]) -> str:
    """The plainest reason of the ones the positions give, so the sheet to fix is named."""
    for position in positions:
        if position.who is not None and member.id not in position.who:
            return f"the card asks for {position.wanted or 'somebody else'}"
    for position in positions:
        if not member.status(position.skill).eligible and position.skill != ANY_SKILL:
            skill = position.skill.replace("_", " ")
            return f"not checked off on '{skill}' (Skills sheet)"
    return f"RAL {member.ral} is below the {min(p.ral for p in positions)} it needs"


# -- whether it is happening at all ---------------------------------------------------------


def _offered(dataset: Dataset) -> set[tuple[str, str]] | None:
    """(activity, block) the target date offers, or None when the day offers nothing.

    A day whose Offerings tab has not been filled in yet offers nothing, and every clinic
    anybody asked for would be an error: a pane full of noise about one thing, which the
    toolbar already says when Solve is pressed. So nothing is checked until something is
    offered.
    """
    offerings = {(o.activity, b) for o in dataset.offerings for b in o.blocks}
    return offerings or None


def _unoffered(statement, request: Request, dataset: Dataset, activity, offered) -> list:
    """Blocks the request puts a clinic in that the day does not run it in.

    Only the date being scheduled can answer this: it is the one day whose Offerings tab has
    been read. A cabin act is not offered at all — it belongs to its cabin on its own day —
    so it is not asked about.
    """
    if offered is None or activity.cabin or activity.day is not None:
        return []
    if statement.during is None or not forced(statement.during) or not forced(statement.on):
        return []
    if dataset.target not in statement.on.items:
        return []
    found = []
    for block in statement.during.items:
        if (activity.id, str(block)) in offered:
            continue
        where = _elsewhere(activity.id, offered)
        found.append(
            Problem(
                request.id,
                f"{activity.name} is not offered in {block} on {dataset.target}{where}",
                day=dataset.target,
                staff=_only(statement.who),
                block=str(block),
            )
        )
    return found


def _elsewhere(activity_id: str, offered: set[tuple[str, str]]) -> str:
    """Where the day does run it, which is usually what the request meant."""
    blocks = sorted(b for a, b in offered if a == activity_id)
    if not blocks:
        return "; the day's Offerings tab does not run it at all"
    return f"; the day runs it in {', '.join(blocks)}"


def _only(who) -> str | None:
    """The one staff member a choice names, if it names one."""
    if who is None or not forced(who) or len(who.items) != 1:
        return None
    return str(who.items[0])


def summary(errors: tuple[Problem, ...]) -> str:
    """A line for the window: how much is wrong, and with how many requests."""
    if not errors:
        return "No errors"
    requests = len({e.request for e in errors})
    return f"{len(errors)} error(s) in {requests} request(s)"
