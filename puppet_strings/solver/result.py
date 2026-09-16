"""What a solve produces."""

from dataclasses import dataclass, field

from puppet_strings.model import Assignment, Priority


@dataclass(frozen=True)
class RequestOutcome:
    """A request copy that was not satisfied, or was deferred to a later date."""

    id: str
    priority: Priority
    description: str


@dataclass(frozen=True)
class Result:
    """The schedule for the target date and the report that goes with it."""

    feasible: bool
    assignments: tuple[Assignment, ...] = ()
    unsatisfied: tuple[RequestOutcome, ...] = ()
    deferred: tuple[RequestOutcome, ...] = ()
    conflicts: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    tier_scores: dict[Priority, int] = field(default_factory=dict)
