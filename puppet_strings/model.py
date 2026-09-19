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
        """The trainee role a `roles.trainee` task resolves to for this status."""
        if self in (SkillStatus.NONE, SkillStatus.NEEDS_SHADOW):
            return SHADOW
        return SCAFFOLDED


SHADOW = "shadow"
SCAFFOLDED = "scaffolded"
TRAINEE_ROLES = (SHADOW, SCAFFOLDED)

# Words for counting things the Puppet Master names out loud: the third Monday of a
# session, the second week of session four. A season never runs to twenty of anything, and
# the Calendar sheet is checked against that, so a number beyond these is a mistake.
ORDINAL_WORDS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
    "twentieth",
)
CARDINAL_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)
MAX_COUNTED = len(ORDINAL_WORDS)

ORDINALS = ORDINAL_WORDS[:6]
POSITION_ROLES = ORDINALS  # a clinic's positions are named by ordinal

# Skills are held by normalized name (`names.normalize`), so a Skills column headed
# "Candle making" and a Positions cell reading "Candle Making" are the same skill.
#
# A lifeguard is an extra person on a water clinic, beyond its facilitator positions.
# Every lifeguard position requires the LIFEGUARD skill at RAL 5.
LIFEGUARD_ROLES = ("lifeguard", "lifeguard_2", "lifeguard_3")
LIFEGUARD_SKILL = "lifeguard"  # the LIFEGUARD column on the Skills tab
LIFEGUARD_RAL = 5

# The groups the request manager sorts requests into to begin with. A group is a label on
# a request, like a tag, so the ones the Puppet Master adds need nothing declared anywhere.
# Requests made from the Offerings tab are in no group: the `generated` tag already tells
# them apart, and a group they filled by the dozen buried everything else.
DEFAULT_GROUPS = ("Special daily requests", "Special weekly requests")

ANY_SKILL = "any"  # a Positions cell reading "Any" needs no checkoff
MAX_RAL = 5


@dataclass(frozen=True)
class Staff:
    """One staff member."""

    name: str
    id: str
    ral: int
    skills: Mapping[str, SkillStatus]
    resting_blocks: frozenset[str] = frozenset()
    # The Skills tab's own word per skill, which says more than the status it maps to:
    # `WCF` and `✓` are both checked off, and the sheet is where that distinction lives.
    written: Mapping[str, str] = field(default_factory=dict)

    def status(self, skill: str | None) -> SkillStatus:
        """Status on a skill by normalized name; no skill counts as checked off."""
        if skill is None:
            return SkillStatus.CHECKED_OFF
        return self.skills.get(skill, SkillStatus.NONE)


@dataclass(frozen=True)
class Position:
    """One staffing slot on an activity, and who is allowed to hold it.

    A clinic says who by the skill its position needs. A cabin act may instead ask for one
    person by name, or for anyone in a category, so `who` narrows the field to those staff
    ids; None means anyone the skill and RAL allow. `wanted` is the sheet's own words for
    what was asked, which is what the app shows and what the ad hoc task is named after.
    """

    role: str
    skill: str | None
    ral: int
    who: frozenset[str] | None = None
    wanted: str = ""

    def allows(self, member: "Staff") -> bool:
        """Whether one staff member may hold this position."""
        if member.ral < self.ral or not member.status(self.skill).eligible:
            return False
        return self.who is None or member.id in self.who


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
    # A cabin act belongs to one cabin on one day, so it carries both; a clinic carries
    # neither and can run on any day it is offered.
    cabin: str = ""
    day: date | None = None
    # What the cabin act board wrote on the card, label by label, for the app to show.
    card: tuple[tuple[str, str], ...] = ()

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
    """One camp day from the Calendar sheet.

    `session` and `week` are the numbers written on the sheet: session 4, week 2 of that
    session. They are what `dates.session.four.second_week` is built from, so a day belongs
    to exactly one session and one week of it.
    """

    date: date
    session: int
    week: int
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
    """One row of the Requests sheet.

    `groups` are the panes of the request manager a request shows up in; a request may be
    in several or in none. `requester` is the staff id of whoever asked for it, or "".
    """

    id: str
    description: str
    skedge: str
    priority: Priority
    weight: float = 1.0
    tags: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    requester: str = ""
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


class Rest(Enum):
    """How much of a day a staff member is resting through."""

    NONE = ""
    ALL_DAY = "all day"
    MORNING = "morning"
    AFTERNOON = "afternoon"


@dataclass(frozen=True)
class Adjustment:
    """A one-day change to what a staff member may do, from the Adjustments sheet.

    `resting` takes them off the whole day or half of it, which is how someone who is ill
    is left out of the mandatory breaks as well as the clinics. `ral_penalty` comes off
    their usual RAL for the day, which is how a short night narrows what they may run.
    """

    date: date
    staff: str
    resting: Rest = Rest.NONE
    ral_penalty: int = 0
    note: str = ""

    def ral_for(self, usual: int) -> int:
        """Their risk assessment level today. It can reach 0, which rules out every clinic."""
        return max(0, usual - self.ral_penalty)

    @property
    def summary(self) -> str:
        """What is different about them today, without their name."""
        parts = []
        if self.resting is Rest.ALL_DAY:
            parts.append("resting all day")
        elif self.resting is not Rest.NONE:
            parts.append(f"resting this {self.resting.value}")
        if self.ral_penalty:
            parts.append(f"down {self.ral_penalty} RAL")
        return " and ".join(parts)

    def describe(self, name: str) -> str:
        """A sentence for the report and the toolbar."""
        text = f"{name} is {self.summary} today"
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
    resting: Mapping[date, Mapping[str, frozenset[str]]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def today_adjustments(self) -> tuple[Adjustment, ...]:
        """The adjustments in effect on the target date, one per staff member."""
        latest = {a.staff: a for a in self.adjustments if a.date == self.target}
        return tuple(latest.values())

    @property
    def session(self) -> int:
        """The number of the session the target falls in."""
        return self.calendar[self.target].session

    @property
    def session_dates(self) -> tuple[date, ...]:
        """Dates of the session containing the target, in order."""
        return self.sessions[self.session]

    @property
    def week_dates(self) -> tuple[date, ...]:
        """Dates of the week of the session containing the target, in order."""
        return self.weeks(self.session)[self.calendar[self.target].week]

    @property
    def season_dates(self) -> tuple[date, ...]:
        """Every date on the calendar, in order."""
        return tuple(sorted(self.calendar))

    @property
    def sessions(self) -> dict[int, tuple[date, ...]]:
        """Each session's dates in order, by session number, lowest number first."""
        grouped: dict[int, list[date]] = {}
        for day in self.season_dates:
            grouped.setdefault(self.calendar[day].session, []).append(day)
        return {session: tuple(grouped[session]) for session in sorted(grouped)}

    def weeks(self, session: int) -> dict[int, tuple[date, ...]]:
        """One session's weeks in order, by week number."""
        grouped: dict[int, list[date]] = {}
        for day in self.sessions.get(session, ()):
            grouped.setdefault(self.calendar[day].week, []).append(day)
        return {week: tuple(grouped[week]) for week in sorted(grouped)}

    def blocks_on(self, day: date) -> tuple[Block, ...]:
        """Blocks that exist on a date, in Blocks sheet order."""
        day_type = self.calendar[day].day_type
        return tuple(b for b in self.blocks.values() if day_type in b.day_types)

    def holds(self, staff_id: str, day: date, block_id: str) -> bool:
        """Whether a date can hold an assignment: the block exists and the person is not resting."""
        if (
            day not in self.calendar
            or self.calendar[day].day_type not in self.blocks[block_id].day_types
        ):
            return False
        return block_id not in self.resting.get(day, {}).get(staff_id, frozenset())
