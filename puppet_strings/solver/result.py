"""What a solve produces."""

from dataclasses import dataclass, field

from puppet_strings.model import Assignment, Priority


@dataclass(frozen=True)
class RequestOutcome:
    """A request copy that was not satisfied, was deferred to a later date, or was inactive."""

    id: str
    priority: Priority
    description: str


@dataclass(frozen=True)
class Change:
    """What one staff member's block held before and after a same-day re-solve."""

    staff: str
    block: str
    before: tuple[Assignment, ...]
    after: tuple[Assignment, ...]


@dataclass(frozen=True)
class Result:
    """The schedule for the target date and the report that goes with it."""

    feasible: bool
    assignments: tuple[Assignment, ...] = ()
    unsatisfied: tuple[RequestOutcome, ...] = ()
    deferred: tuple[RequestOutcome, ...] = ()
    inactive: tuple[RequestOutcome, ...] = ()
    conflicts: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    changes: tuple[Change, ...] = ()
    tier_scores: dict[Priority, int] = field(default_factory=dict)
