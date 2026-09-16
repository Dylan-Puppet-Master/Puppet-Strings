"""Small datasets for solver tests, built in Python rather than loaded from fixtures."""

from datetime import date, time, timedelta

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
    "lunch_break": ("12:30", "13:00", ("break_slots",)),
    "pm_break": ("13:00", "13:30", ("break_slots",)),
    "work_projects": ("13:30", "14:00", ()),
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
    """positions: (skill or None, ral) per position."""
    roles = ("first", "second", "third")
    return Activity(
        name=name,
        id=normalize(name),
        category=category,
        slots=6,
        positions=tuple(Position(roles[i], s, r) for i, (s, r) in enumerate(positions)),
        lifeguards=lifeguards,
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
    return Dataset(
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


def published(day, *rows):
    """rows: (staff, activity, role, block)."""
    return {
        day: tuple(
            Assignment(normalize(s), normalize(a), r, day, b, "offering") for s, a, r, b in rows
        )
    }


def enjoyment(values: dict[tuple[str, str], float]) -> dict[str, Metric]:
    table = {(normalize(s), normalize(a)): v for (s, a), v in values.items()}
    return {"enjoyment": Metric("enjoyment", ("staff", "activity"), 1, 5, table)}
