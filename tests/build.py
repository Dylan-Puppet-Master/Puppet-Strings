"""Small datasets for solver tests, built in Python rather than loaded from fixtures."""

from dataclasses import replace
from datetime import date, time, timedelta

from puppet_strings.generate import generated_requests
from puppet_strings.model import (
    MAIN_SEASON,
    WEEKDAY,
    WEEKEND,
    Activity,
    Assignment,
    Block,
    Dataset,
    MappingTable,
    Offering,
    Position,
    Priority,
    Request,
    SkillStatus,
    Span,
    Staff,
)
from puppet_strings.names import normalize

TARGET = date(2026, 9, 16)
OK = SkillStatus.CHECKED_OFF
TRAINER = SkillStatus.TRAINER
SCAF = SkillStatus.NEEDS_SCAFFOLD
SHADOW = SkillStatus.NEEDS_SHADOW

BLOCKS = {
    "clinic_1": ("09:15", "10:30", ("all_clinics",)),
    "clinic_2": ("10:45", "12:00", ("all_clinics",)),
    "lunch": ("12:00", "13:00", ("meals",)),
    "clinic_3": ("14:00", "15:15", ("all_clinics",)),
    "clinic_4": ("15:45", "17:00", ("all_clinics",)),
    "playstation": ("17:00", "18:00", ()),
}


SKILL_NAMES = {
    "archery_1_2": "Archery 1 & 2",
    "candle_making": "Candle making",
    "riflery": "Riflery",
    "gravity_zip_line_1st": "Gravity Zip Line 1st",
    "gravity_zip_line_2nd": "Gravity Zip Line 2nd",
    "blacksmithing": "Blacksmithing",
    "canoe": "Canoe",
    "lifeguard": "LIFEGUARD",
    "muay_thai": "Muay Thai",
}


def staff(name: str, ral: int = 5, **skills: SkillStatus) -> Staff:
    """Keyword names are looked up in SKILL_NAMES so tests can write archery_1_2=OK."""
    return Staff(name, normalize(name), ral, {SKILL_NAMES[k]: v for k, v in skills.items()})


def clinic(name, *positions, category="arts", lifeguards=0):
    """positions: (skill or None, ral) per facilitator position; lifeguards are added."""
    roles = ("first", "second", "third")
    facilitators = [Position(roles[i], s, r) for i, (s, r) in enumerate(positions)]
    extra = [Position(role, "LIFEGUARD", 5) for role in ("lifeguard", "lifeguard_2")[:lifeguards]]
    return Activity(
        name=name,
        id=normalize(name),
        category=category,
        slots=6,
        positions=tuple(facilitators + extra),
        double=name.endswith("(DBL)"),
    )


def cabin_act(cabin, name, *wants, category="cabin_act", day=TARGET):
    """A cabin act. Each want is (the words asked for, the staff ids that answer to them)."""
    roles = ("first", "second", "third")
    positions = tuple(
        Position(roles[i], None, 1, frozenset(who), wanted) for i, (wanted, who) in enumerate(wants)
    )
    return Activity(
        name=name,
        id=normalize(f"{cabin} {name} {day}"),
        category=category,
        slots=0,
        positions=positions,
        cabin=cabin,
        day=day,
    )


def request(id, skedge, priority=Priority.HIGH, weight=1.0):
    return Request(id, id, skedge, priority, weight)


def resting(member, blocks, half=None):
    """A copy of a staff member resting through a half of the day, or all of it."""
    midday = time(12, 0)
    ids = [
        name
        for name, (start, _, _) in blocks.items()
        if half is None or (time.fromisoformat(start) < midday) == (half == "morning")
    ]
    return replace(member, resting_blocks=frozenset(ids))


def dataset(
    members,
    activities,
    offerings=(),
    requests=(),
    published=None,
    categories=None,
    mappings=None,
    target=TARGET,
    blocks=None,
    rests=None,
):
    """A one-week session around `target`. `rests` maps a date to {staff id: resting block ids}."""
    blocks = blocks or BLOCKS
    block_objects = {
        name: Block(
            name,
            time.fromisoformat(s),
            time.fromisoformat(e),
            frozenset({WEEKDAY, WEEKEND}),
            frozenset({MAIN_SEASON}),
            frozenset(c) | {"all"},
        )
        for name, (s, e, c) in blocks.items()
    }
    categories_by_block = {c for b in block_objects.values() for c in b.categories}
    staff_by_id = {s.id: s for s in members}
    activity_by_id = {a.id: a for a in activities}
    span = Span(
        name="Session 1",
        id="session_1",
        start=target - timedelta(days=3),
        end=target + timedelta(days=3),
        program_type=MAIN_SEASON,
        session=1,
    )
    rests = rests or {}
    if target in rests:
        staff_by_id = {
            i: replace(s, resting_blocks=rests[target].get(i, frozenset()))
            for i, s in staff_by_id.items()
        }
    working = frozenset(i for i, s in staff_by_id.items() if s.resting_blocks != set(block_objects))
    built = Dataset(
        target=target,
        staff=staff_by_id,
        staff_categories={
            "all": working,
            "clinic_trainers": frozenset(
                s.id for s in members if any(v.can_scaffold for v in s.skills.values())
            )
            & working,
            **{
                k: frozenset(normalize(n) for n in v) & working
                for k, v in (categories or {}).items()
            },
        },
        activities=activity_by_id,
        activity_categories={
            "all": frozenset(activity_by_id),
            **{
                c: frozenset(a.id for a in activities if a.category == c)
                for c in {a.category for a in activities}
            },
        },
        blocks=block_objects,
        block_categories={
            c: frozenset(b.id for b in block_objects.values() if c in b.categories)
            for c in categories_by_block
        },
        calendar={d: span.day(d) for d in span.dates},
        spans=(span,),
        offerings=tuple(Offering(normalize(a), tuple(b)) for a, b in offerings),
        requests=tuple(requests),
        mappings=mappings or {},
        published=published or {},
        resting=rests,
    )
    return replace(built, requests=built.requests + tuple(generated_requests(built)))


def published(day, *rows, blocks=None):
    """rows: (staff, activity, role, block[, minutes]). Whole block unless minutes given.

    An activity in quotes is a quoted task.
    """
    blocks = blocks or BLOCKS
    assignments = []
    for row in rows:
        s, a, r, b = row[:4]
        start, end = (time.fromisoformat(t) for t in blocks[b][:2])
        length = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        minutes = row[4] if len(row) > 4 else length
        activity = a.strip("'") if a.startswith("'") else normalize(a)
        assignments.append(
            Assignment(normalize(s), activity, r, day, b, start, minutes, "offering")
        )
    return {day: tuple(assignments)}


def preference(values: dict[tuple[str, str], float], default: float | None = None):
    """A 1-5 preference mapping keyed by staff and clinic."""
    table = {(normalize(s), normalize(a)): v for (s, a), v in values.items()}
    keys = ("staff", "activities.clinics")
    return {"preference": MappingTable("preference", keys, "numeric", table, 1, 5, default)}


BUDDY_DEFAULT = "ANY 1 {staff - staff.counselor - staff.director}"


def buddies(rows: dict[str, str], default: str | None = BUDDY_DEFAULT):
    """Each counselor's buddy HERO, who covers their cabin at dinner, by name."""
    table = {(normalize(c),): normalize(b) for c, b in rows.items()}
    value = "{staff - staff.counselor}"
    return {"buddy": MappingTable("buddy", ("staff.counselor",), value, table, default=default)}
