"""Clinic_Data: the combined tab with one row per clinic.

Columns: Clinic_Name, Slots, Staff_Required (or Staff_Requested), RAL_Required, Category,
and optionally LG_Required. RAL_Required has one digit per position, in position order.

LG_Required counts lifeguards in addition to Staff_Required: a water clinic with one
facilitator and one lifeguard has Staff_Required 1 and LG_Required 1. Lifeguard positions
need the LIFEGUARD skill at RAL 5.
"""

from collections.abc import Mapping

from puppet_strings.model import (
    ANY_SKILL,
    LIFEGUARD_RAL,
    LIFEGUARD_ROLES,
    LIFEGUARD_SKILL,
    POSITION_ROLES,
    Activity,
    Position,
)
from puppet_strings.names import check_unique, normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

DOUBLE_SUFFIX = "(DBL)"


def parse_clinics(
    table: Table, position_skills: Mapping[str, tuple[str | None, ...]]
) -> dict[str, Activity]:
    """Activities by id. `position_skills` maps clinic name to the skill of each position."""
    where = "Clinic_Data"
    rows = header_rows(table, ("Clinic_Name", "RAL_Required", "Category"), where)
    activities = {}
    for row in rows:
        name = row["Clinic_Name"]
        cell = f"{where} row '{name}'"
        staff_count = parse_int(row.get("Staff_Required") or row.get("Staff_Requested", ""), cell)
        rals = row["RAL_Required"]
        if len(rals) != staff_count or not rals.isdigit():
            raise LoadError(
                f"{cell}: RAL_Required '{rals}' must be {staff_count} digits, one per position"
            )
        if staff_count > len(POSITION_ROLES):
            raise LoadError(f"{cell}: at most {len(POSITION_ROLES)} positions are supported")
        skills = position_skills.get(name, ())
        positions = [
            Position(role=POSITION_ROLES[i], skill=_skill(skills, i), ral=int(rals[i]))
            for i in range(staff_count)
        ]
        lifeguards = parse_int(row.get("LG_Required") or "0", cell)
        if lifeguards > len(LIFEGUARD_ROLES):
            raise LoadError(f"{cell}: at most {len(LIFEGUARD_ROLES)} lifeguards are supported")
        positions += [
            Position(role=LIFEGUARD_ROLES[i], skill=LIFEGUARD_SKILL, ral=LIFEGUARD_RAL)
            for i in range(lifeguards)
        ]
        activity = Activity(
            name=name,
            id=normalize(name),
            category=normalize(row["Category"]),
            slots=parse_int(row.get("Slots") or "0", cell),
            positions=tuple(positions),
            double=name.endswith(DOUBLE_SUFFIX),
        )
        activities[activity.id] = activity
    check_unique(where, [a.name for a in activities.values()])
    return activities


def _skill(skills: tuple[str | None, ...], index: int) -> str | None:
    if index >= len(skills):
        return None
    skill = skills[index]
    if not skill or skill == ANY_SKILL:
        return None
    return skill
