"""Domain objects shared by the sheet loaders, Skedge, the solver, and the app."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
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

# The groups the request manager sorts requests onto to begin with. A group is a label on
# a request, so the ones the Puppet Master adds need nothing declared anywhere. Requests
# made from the Offerings tab are on no shelf: the `generated` tag already tells them
# apart, and a group they filled by the dozen buried everything else.
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
    """A time block from the Blocks sheet.

    It exists on a day when the day's programme is one of `program_types` and the day is one
    of the kinds in `day_types`: `weekday, weekend` is every day of a span, `first_day` only
    the day it starts.
    """

    id: str
    start: time
    end: time
    day_types: frozenset[str]
    program_types: frozenset[str]
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
    """One camp day, worked out from the span of the Calendar sheet that covers it.

    `day_types` are the kinds this day is, which is how the Blocks sheet says a block exists
    on it: a day is `weekday` or `weekend` by the calendar, and also `first_day` or
    `last_day` when it is one end of its span. A day is usually two of them.
    """

    date: date
    span: str  # the id of the Calendar row covering it
    session: int | None  # 1, 2, 3 … for a main season span, None for anything else
    week: int  # which week of its span, counting seven days at a time from the start
    day_types: frozenset[str]
    program_type: str


MAIN_SEASON = "main_season"
OTHER_PROGRAM = "other"
PROGRAM_TYPES = (MAIN_SEASON, OTHER_PROGRAM)

FIRST_DAY = "first_day"
LAST_DAY = "last_day"
WEEKDAY = "weekday"
WEEKEND = "weekend"
DAY_TYPES = (FIRST_DAY, LAST_DAY, WEEKDAY, WEEKEND)

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class Span:
    """One row of the Calendar sheet: a named run of days running one programme.

    A main season span is also numbered, in sheet order, which is what `dates.session.four`
    is named after. Anything else is named only, and is reached as `dates.other.<name>`.
    """

    name: str
    id: str
    start: date
    end: date
    program_type: str
    session: int | None = None

    @property
    def dates(self) -> tuple[date, ...]:
        """Every day it covers, start and end included."""
        length = (self.end - self.start).days + 1
        return tuple(self.start + timedelta(days=i) for i in range(length))

    def week_of(self, day: date) -> int:
        """Which week of the span a day falls in, counting seven days from the start."""
        return (day - self.start).days // DAYS_PER_WEEK + 1

    @property
    def weeks(self) -> int:
        """How many weeks it runs to, the last one short if it does not divide evenly."""
        return self.week_of(self.end)

    def types_of(self, day: date) -> frozenset[str]:
        """The kinds of day this one is."""
        kinds = {WEEKDAY if day.weekday() < 5 else WEEKEND}
        if day == self.start:
            kinds.add(FIRST_DAY)
        if day == self.end:
            kinds.add(LAST_DAY)
        return frozenset(kinds)

    def day(self, day: date) -> "CalendarDay":
        """How the span reads one of its days."""
        return CalendarDay(
            date=day,
            span=self.id,
            session=self.session,
            week=self.week_of(day),
            day_types=self.types_of(day),
            program_type=self.program_type,
        )


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
    """One row of a Requests tab.

    `group` is the shelf of the request manager it sits on, or "" for none. A request is on
    one shelf and no more, the way a piece of paper is in one folder. `requester` is the
    staff id of whoever asked for it, or "".

    `description` is for people and may be left empty; the id is what names the request
    everywhere it is referred to, and is not made out of the description.

    `home` is the tab it is written on and was read from — a session's Clinics or Special
    tab, or the season's. It is not a column: the tab a row sits on is what says it, which
    is why moving a request between sessions is a cut and paste on the sheet.
    """

    id: str
    description: str
    skedge: str
    priority: Priority
    weight: float = 1.0
    tags: tuple[str, ...] = ()
    group: str = ""
    requester: str = ""
    created: date | None = None
    home: str = ""


NUMERIC = "numeric"  # what a mapping's `value` says when it gives a number, not a name


def is_numeric(value: str) -> bool:
    """Whether a Mappings tab `value` says the mapping gives numbers rather than names."""
    return value.strip().lower() == NUMERIC


@dataclass(frozen=True)
class MappingTable:
    """A table from keys to a value, declared on the Mappings tab.

    `keys` are Skedge set expressions, one per key column, saying what each may hold:
    `staff.counselor`, `{staff.all - staff.counselor}`, or a bare namespace such as
    `staff` for any name in it. `value` is the same for what a row gives, or `numeric`.

    A numeric mapping is a scale of ratings: `rows` hold numbers between `scale_min` and
    `scale_max`, and `default` is what a key with no row is worth (the bottom of the scale
    if it is None). Any other mapping gives a name: `rows` hold identifiers (a date's in
    ISO form), and `default` is a Skedge phrase, such as `ANY_1_OF {staff.office}`, to
    stand in for a key with no row, or None when every key needs one.

    Key identifiers are strings throughout, a date's in ISO form, so a row reads the same
    whichever namespace its keys come from.
    """

    name: str
    keys: tuple[str, ...]
    value: str
    rows: Mapping[tuple[str, ...], float | str]
    scale_min: float | None = None
    scale_max: float | None = None
    default: float | str | None = None

    @property
    def numeric(self) -> bool:
        """Whether a row is a number on a scale rather than a name."""
        return is_numeric(self.value)

    @property
    def missing(self) -> float:
        """The number used for a key with no row, in a numeric mapping."""
        return self.scale_min if self.default is None else self.default

    def normalized(self, key: tuple[str, ...]) -> float:
        """Value for this key scaled to 0..1, using the default when the key has no row."""
        value = self.rows.get(key, self.missing)
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
    spans: tuple[Span, ...] = ()
    offerings: tuple[Offering, ...] = ()
    requests: tuple[Request, ...] = ()
    mappings: Mapping[str, MappingTable] = field(default_factory=dict)
    published: Mapping[date, tuple[Assignment, ...]] = field(default_factory=dict)
    baseline: tuple[Assignment, ...] | None = None
    adjustments: tuple[Adjustment, ...] = ()
    resting: Mapping[date, Mapping[str, frozenset[str]]] = field(default_factory=dict)
    # Who an EXCLUDE has taken out of a day, by date: staff id -> block -> the label to
    # write where their assignments would have been. They hold nothing in those blocks and
    # nothing is asked of them there; `resting` carries the same blocks, which is what the
    # solver reads, and this carries the words, which is what the published views read.
    excluded: Mapping[date, Mapping[str, Mapping[str, str]]] = field(default_factory=dict)
    # Who the span's Staff Categories sheet does not name, and so is not at camp this span.
    # The Skills sheet keeps everyone who ever worked here, and the ones who have left or
    # are here another session are nothing to do with this day: they hold no assignment,
    # and nothing published says their name. An empty set is everybody being here.
    away: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()

    @property
    def at_camp(self) -> tuple[str, ...]:
        """The staff this span has, in Skills sheet order. A day is only ever about them."""
        return tuple(i for i in self.staff if i not in self.away)

    def excused(self, staff_id: str, block: str, day: date | None = None) -> str:
        """What an EXCLUDE wrote over this slot, or "" if the person is in the schedule."""
        excluded = self.excluded.get(day or self.target, {})
        return excluded.get(staff_id, {}).get(block, "")

    @property
    def today_adjustments(self) -> tuple[Adjustment, ...]:
        """The adjustments in effect on the target date, one per staff member."""
        latest = {a.staff: a for a in self.adjustments if a.date == self.target}
        return tuple(latest.values())

    @property
    def session(self) -> int | None:
        """The number of the session the target falls in, or None outside the main season."""
        return self.calendar[self.target].session

    @property
    def this_span(self) -> Span:
        """The Calendar row the target falls in, whatever programme it runs."""
        return self.span(self.calendar[self.target].span)

    def span(self, span_id: str) -> Span:
        """One Calendar row by its id."""
        return next(s for s in self.spans if s.id == span_id)

    @property
    def session_dates(self) -> tuple[date, ...]:
        """Dates of the span containing the target, in order."""
        return self.span_dates(self.this_span)

    @property
    def week_dates(self) -> tuple[date, ...]:
        """Dates of the week of the span containing the target, in order."""
        return self.span_weeks(self.this_span)[self.calendar[self.target].week]

    @property
    def season_dates(self) -> tuple[date, ...]:
        """Every date on the calendar, in order."""
        return tuple(sorted(self.calendar))

    @property
    def sessions(self) -> dict[int, Span]:
        """Each main season span by its number, lowest first."""
        return {s.session: s for s in self.spans if s.session is not None}

    def span_dates(self, span: Span) -> tuple[date, ...]:
        """One span's dates in order."""
        return tuple(d for d in span.dates if d in self.calendar)

    def span_weeks(self, span: Span) -> dict[int, tuple[date, ...]]:
        """One span's weeks in order, by week number."""
        grouped: dict[int, list[date]] = {}
        for day in self.span_dates(span):
            grouped.setdefault(span.week_of(day), []).append(day)
        return {week: tuple(grouped[week]) for week in sorted(grouped)}

    def blocks_on(self, day: date) -> tuple[Block, ...]:
        """Blocks that exist on a date, in Blocks sheet order."""
        entry = self.calendar[day]
        return tuple(b for b in self.blocks.values() if block_runs_on(b, entry))

    def holds(self, staff_id: str, day: date, block_id: str) -> bool:
        """Whether a date can hold an assignment: the block exists and the person is not resting."""
        if day not in self.calendar or not block_runs_on(self.blocks[block_id], self.calendar[day]):
            return False
        return block_id not in self.resting.get(day, {}).get(staff_id, frozenset())


def block_runs_on(block: Block, day: CalendarDay) -> bool:
    """Whether a block exists on a day: its programme, and any one of the day's kinds."""
    return day.program_type in block.program_types and bool(day.day_types & block.day_types)
