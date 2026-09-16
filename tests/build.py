"""Small datasets for solver tests, built in Python rather than loaded from fixtures."""

from dataclasses import replace
from datetime import date, time, timedelta

from puppet_strings.generate import generated_requests
from puppet_strings.model import (
    Activity,
    Assignment,
    Block,
    CalendarDay,
    Dataset,
    Metric,
    Offering,
    Position,
    Priority,
    Request,
    SkillStatus,
    Staff,
)
from puppet_strings.names import normalize

TARGET = date(2026, 9, 16)
OK = SkillStatus.CHECKED_OFF
TRAINER = SkillStatus.TRAINER
SCAF = SkillStatus.NEEDS_SCAFFOLD
SHADOW = SkillStatus.NEEDS_SHADOW

BLOCKS = {
    "clinic_1": ("09:15", "10:30", ("any_clinic",)),
    "clinic_2": ("10:45", "12:00", ("any_clinic",)),
    "lunch": ("12:00", "13:00", ("meals",)),
    "clinic_3": ("14:00", "15:15", ("any_clinic",)),
    "clinic_4": ("15:45", "17:00", ("any_clinic",)),
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


def request(id, skedge, priority=Priority.HIGH, weight=1.0):
    return Request(id, id, skedge, priority, weight)


def dataset(
    members,
    activities,
    offerings=(),
    requests=(),
    published=None,
    categories=None,
    metrics=None,
    target=TARGET,
    blocks=None,
):
    blocks = blocks or BLOCKS
    block_objects = {
        name: Block(
            name,
            time.fromisoformat(s),
            time.fromisoformat(e),
            frozenset({"regular"}),
            frozenset(c) | {"any"},
        )
        for name, (s, e, c) in blocks.items()
    }
    categories_by_block = {c for b in block_objects.values() for c in b.categories}
    staff_by_id = {s.id: s for s in members}
    activity_by_id = {a.id: a for a in activities}
    session = [target - timedelta(days=3) + timedelta(days=i) for i in range(7)]
    built = Dataset(
        target=target,
        staff=staff_by_id,
        staff_categories={
            "all": frozenset(staff_by_id),
            "clinic_trainers": frozenset(
                s.id for s in members if any(v.can_scaffold for v in s.skills.values())
            ),
            **{k: frozenset(normalize(n) for n in v) for k, v in (categories or {}).items()},
        },
        activities=activity_by_id,
        activity_categories={
            "any_clinic": frozenset(activity_by_id),
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
        calendar={d: CalendarDay(d, "session_1", "regular") for d in session},
        offerings=tuple(Offering(normalize(a), tuple(b)) for a, b in offerings),
        requests=tuple(requests),
        metrics=metrics or {},
        published=published or {},
    )
    return replace(built, requests=built.requests + tuple(generated_requests(built)))


def published(day, *rows, blocks=None):
    """rows: (staff, activity, role, block[, minutes]). Whole block unless minutes given.

    An activity in quotes is an ad hoc task.
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


def enjoyment(values: dict[tuple[str, str], float], default: float | None = None):
    """A 1-5 enjoyment metric keyed by staff and activity."""
    table = {(normalize(s), normalize(a)): v for (s, a), v in values.items()}
    return {"enjoyment": Metric("enjoyment", ("staff", "activity"), 1, 5, table, default)}
