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
from puppet_strings.sheets.skills import PositionSkills
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

DOUBLE_SUFFIX = "(DBL)"


def parse_clinics(
    table: Table,
    position_skills: PositionSkills,
    known_skills: Mapping[str, str],
) -> dict[str, Activity]:
    """Activities by id.

    `position_skills` maps clinic name to the skill of each position, and `known_skills` is
    every skill the Skills tab has a column for. Every position of every clinic must name a
    skill, or `Any` where none is needed; a missing Positions row or a blank cell is a
    LoadError listing every such clinic. Reading either as "no skill required" is what let
    staff who are not checked off be given clinics to run.
    """
    where = "Clinic_Data"
    rows = header_rows(table, ("Clinic_Name", "RAL_Required", "Category"), where)
    activities = {}
    problems: list[str] = []
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
        row_positions = position_skills.get(normalize(name))
        if row_positions is None:
            problems.append(f"{name}: no row on the Positions tab")
            skills: tuple[str | None, ...] = ()
        else:
            skills = row_positions.skills
            problems += _blank_positions(name, skills, staff_count)
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
        if lifeguards and LIFEGUARD_SKILL not in known_skills:
            problems.append(f"{name}: needs lifeguards, but the Skills tab has no LIFEGUARD column")
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
    problems += [
        f"{row.name}: a Positions row for no clinic on {where}"
        for clinic, row in sorted(position_skills.items())
        if clinic not in activities
    ]
    if problems:
        raise LoadError(
            "Positions and clinics do not line up, so these clinics would take any staff:\n  "
            + "\n  ".join(problems)
            + "\nWrite 'Any' where a position needs no checkoff."
        )
    return activities


def _blank_positions(name: str, skills: tuple[str | None, ...], staff_count: int) -> list[str]:
    """One line per position the Positions row leaves blank; `Any` is how to say "no skill"."""
    return [
        f"{name}: the {POSITION_ROLES[i]} position's cell is blank on the Positions tab"
        for i in range(staff_count)
        if i >= len(skills) or not skills[i]
    ]


def _skill(skills: tuple[str | None, ...], index: int) -> str | None:
    if index >= len(skills):
        return None
    skill = skills[index]
    if not skill or skill == ANY_SKILL:
        return None
    return skill
