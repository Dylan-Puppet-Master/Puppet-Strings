"""Domain objects shared by the sheet loaders, Skedge, the solver, and the app."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum


class SkillStatus(Enum):
    """A staff member's standing on one skill, as recorded on the Skills sheet."""

    CHECKED_OFF = "checked off"
    TRAINER = "trainer"
    NEEDS_SCAFFOLD = "needs scaffold"
    NEEDS_SHADOW = "needs shadow"
    NONE = "none"

    @property
    def eligible(self) -> bool:
        """Whether the staff member may fill a position requiring this skill."""
        return self in (SkillStatus.CHECKED_OFF, SkillStatus.TRAINER)

    @property
    def can_scaffold(self) -> bool:
        """Whether the staff member may supervise a scaffolded trainee on this skill."""
        return self is SkillStatus.TRAINER

    @property
    def trainee_role(self) -> str:
        """The trainee role a `role.trainee` task resolves to for this status."""
        if self in (SkillStatus.NONE, SkillStatus.NEEDS_SHADOW):
            return SHADOW
        return SCAFFOLDED


SHADOW = "shadow"
SCAFFOLDED = "scaffolded"
TRAINEE_ROLES = (SHADOW, SCAFFOLDED)
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")
POSITION_ROLES = ORDINALS  # a clinic's positions are named by ordinal

# A lifeguard is an extra person on a water clinic, beyond its facilitator positions.
# Every lifeguard position requires the LIFEGUARD skill at RAL 5.
LIFEGUARD_ROLES = ("lifeguard", "lifeguard_2", "lifeguard_3")
LIFEGUARD_SKILL = "LIFEGUARD"
LIFEGUARD_RAL = 5

ANY_SKILL = "Any"
MAX_RAL = 5


@dataclass(frozen=True)
class Staff:
    """One staff member."""

    name: str
    id: str
    ral: int
    skills: Mapping[str, SkillStatus]
    available: bool = True

    def status(self, skill: str | None) -> SkillStatus:
        """Status on a skill; a position without a skill counts as checked off."""
        if skill is None:
            return SkillStatus.CHECKED_OFF
        return self.skills.get(skill, SkillStatus.NONE)


@dataclass(frozen=True)
class Position:
    """One staffing slot on a clinic."""

    role: str
    skill: str | None
    ral: int


@dataclass(frozen=True)
class Activity:
    """A clinic from Clinic_Data.

    `positions` holds the facilitator positions (first, second, ...) followed by any
    lifeguard positions (lifeguard, lifeguard_2, ...).
    """

    name: str
    id: str
    category: str
    slots: int
    positions: tuple[Position, ...]
    double: bool = False

    def position(self, role: str) -> Position | None:
        """The position with this role, if any."""
        return next((p for p in self.positions if p.role == role), None)


@dataclass(frozen=True)
class Block:
    """A time block from the Blocks sheet."""

    id: str
    start: time
    end: time
    day_types: frozenset[str]
    categories: frozenset[str]

    @property
    def minutes(self) -> int:
        """Length in minutes."""
        return _minutes(self.end) - _minutes(self.start)

    @property
    def start_minute(self) -> int:
        """Start as minutes after midnight."""
        return _minutes(self.start)

    @property
    def end_minute(self) -> int:
        """End as minutes after midnight."""
        return _minutes(self.end)

    def overlaps(self, other: "Block") -> bool:
        """Whether the two blocks share any time."""
        return _minutes(self.start) < _minutes(other.end) and _minutes(other.start) < _minutes(
            self.end
        )

    def gap_to(self, other: "Block") -> int:
        """Minutes from this block's end to the other's start; negative if not after."""
        return _minutes(other.start) - _minutes(self.end)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def minute_to_time(minute: int) -> time:
    """Minutes after midnight as a time of day."""
    return time(minute // 60, minute % 60)


@dataclass(frozen=True)
class CalendarDay:
    """One camp day from the Calendar sheet."""

    date: date
    session: str
    day_type: str


class Priority(Enum):
    """Request priority tiers, highest first.

    `CLINIC` and `STABILITY` are the solver's own: `CLINIC` comes from the Offerings tab
    and `STABILITY` holds a published schedule together during a same-day change.
    """

    MUST_HAPPEN = "MUST_HAPPEN"
    CLINIC = "CLINIC"
    STABILITY = "STABILITY"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def hard(self) -> bool:
        """Whether the tier is a hard constraint."""
        return self is Priority.MUST_HAPPEN


SOFT_TIERS = (
    Priority.CLINIC,
    Priority.STABILITY,
    Priority.HIGH,
    Priority.MEDIUM,
    Priority.LOW,
)
WRITABLE_PRIORITIES = tuple(p for p in Priority if p is not Priority.STABILITY)


@dataclass(frozen=True)
class Request:
    """One row of the Requests sheet."""

    id: str
    description: str
    skedge: str
    priority: Priority
    weight: float = 1.0
    tags: tuple[str, ...] = ()
    created: date | None = None


@dataclass(frozen=True)
class Metric:
    """A numeric table keyed by assignment fields, with its declared scale.

    `default` is what a key with no row is worth; without one that is the bottom of the
    scale, so an unrated pairing scores nothing.
    """

    name: str
    keys: tuple[str, ...]
    scale_min: float
    scale_max: float
    values: Mapping[tuple[str, ...], float]
    default: float | None = None

    @property
    def missing(self) -> float:
        """The value used for a key with no row."""
        return self.scale_min if self.default is None else self.default

    def normalized(self, key: tuple[str, ...]) -> float:
        """Value for this key scaled to 0..1, using the default when the key has no row."""
        value = self.values.get(key, self.missing)
        return (value - self.scale_min) / (self.scale_max - self.scale_min)


@dataclass(frozen=True)
class Assignment:
    """One staff member doing one thing in one block on one date.

    `activity` is an activity id for clinics or the quoted text of an ad hoc task.
    `role` is a position role, a trainee role, or None for ad hoc tasks.
    `start` and `minutes` place the task inside its block; a clinic fills the whole block,
    an ad hoc task with `FOR` may fill part of it.
    """

    staff: str
    activity: str
    role: str | None
    date: date
    block: str
    start: time
    minutes: int
    source: str = ""

    @property
    def end_minute(self) -> int:
        """End as minutes after midnight."""
        return _minutes(self.start) + self.minutes


@dataclass(frozen=True)
class Adjustment:
    """A one-day change to what a staff member may do, from the Adjustments sheet.

    `available` false takes them off the day altogether, which is how someone who is sick
    is left out of the mandatory breaks as well as the clinics. `ral` lowers their risk
    assessment level for the day, which is how a short night narrows what they may run.
    """

    date: date
    staff: str
    available: bool = True
    ral: int | None = None
    note: str = ""

    def describe(self, name: str) -> str:
        """A sentence for the report and the toolbar."""
        if not self.available:
            text = f"{name} is not working today"
        else:
            text = f"{name} is RAL {self.ral} today"
        return f"{text} ({self.note})" if self.note else text


@dataclass(frozen=True)
class Offering:
    """A clinic offered on the target date in one or more blocks."""

    activity: str
    blocks: tuple[str, ...]


@dataclass(frozen=True)
class Dataset:
    """Everything the solver needs for one target date, loaded from the sheets."""

    target: date
    staff: Mapping[str, Staff]
    staff_categories: Mapping[str, frozenset[str]]
    activities: Mapping[str, Activity]
    activity_categories: Mapping[str, frozenset[str]]
    blocks: Mapping[str, Block]
    block_categories: Mapping[str, frozenset[str]]
    calendar: Mapping[date, CalendarDay]
    offerings: tuple[Offering, ...] = ()
    requests: tuple[Request, ...] = ()
    metrics: Mapping[str, Metric] = field(default_factory=dict)
    published: Mapping[date, tuple[Assignment, ...]] = field(default_factory=dict)
    baseline: tuple[Assignment, ...] | None = None
    adjustments: tuple[Adjustment, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def today_adjustments(self) -> tuple[Adjustment, ...]:
        """The adjustments in effect on the target date, one per staff member."""
        latest = {a.staff: a for a in self.adjustments if a.date == self.target}
        return tuple(latest.values())

    @property
    def session_dates(self) -> tuple[date, ...]:
        """Dates of the session containing the target, in order."""
        session = self.calendar[self.target].session
        return tuple(sorted(d for d, day in self.calendar.items() if day.session == session))

    def blocks_on(self, day: date) -> tuple[Block, ...]:
        """Blocks that exist on a date, by start time."""
        day_type = self.calendar[day].day_type
        return tuple(
            sorted(
                (b for b in self.blocks.values() if day_type in b.day_types),
                key=lambda b: (b.start, b.end),
            )
        )
