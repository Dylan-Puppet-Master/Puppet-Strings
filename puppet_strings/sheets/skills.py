"""Skills: who is checked off on what, and which skill each clinic position needs.

Main tab layout:
  row 1: skill group headings (ignored)
  row 2: skill name; blank marks a date column, which is skipped
  row 3: rank ("1st", "2nd", "1st CW") or blank
  rows 4+: staff name, RAL, a count (ignored), then one status cell per column

A skill's full name is row 2 plus row 3, e.g. "Canopy Tour 1st", matching the
Positions tab, which maps Clinic_Name to the skill of its 1st, 2nd and 3rd position. The
two tabs are matched by normalized name, so "Candle making" and "Candle Making" agree.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from puppet_strings.model import ANY_SKILL, POSITION_ROLES, SkillStatus, Staff
from puppet_strings.names import check_unique, normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows

# Cell text (lowercased, stripped) -> status. Edit here when the sheet vocabulary changes.
STATUS_WORDS = {
    "✓": SkillStatus.CHECKED_OFF,
    "wcf": SkillStatus.CHECKED_OFF,
    "trainer": SkillStatus.TRAINER,
    "w/ scaf": SkillStatus.NEEDS_SCAFFOLD,
    "w/scaf": SkillStatus.NEEDS_SCAFFOLD,
    "brief scaf": SkillStatus.NEEDS_SCAFFOLD,
    "w/ shadow": SkillStatus.NEEDS_SHADOW,
    "": SkillStatus.NONE,
    ".": SkillStatus.NONE,
    "past ex": SkillStatus.NONE,
    "interested": SkillStatus.NONE,
}


@dataclass(frozen=True)
class ClinicPositions:
    """One Positions row: the tab's own spelling of the clinic, and each position's skill."""

    name: str
    skills: tuple[str | None, ...]  # None where the cell is blank


# Keyed by normalized clinic name, so Clinic_Data and Positions need not agree on case.
PositionSkills = dict[str, ClinicPositions]

HEADER_ROWS = 3
NAME_COLUMN = 0
RAL_COLUMN = 1
FIRST_SKILL_COLUMN = 3


def parse_skills(table: Table) -> tuple[dict[str, Staff], list[str]]:
    """Staff by id, plus warnings for cells whose text is not in STATUS_WORDS."""
    where = "Skills"
    if len(table) <= HEADER_ROWS:
        raise LoadError(f"{where}: expected {HEADER_ROWS} header rows and staff rows below")
    skill_columns = _skill_columns(table)
    staff: dict[str, Staff] = {}
    warnings: list[str] = []
    for cells in table[HEADER_ROWS:]:
        name = cells[NAME_COLUMN].strip() if cells else ""
        if not name:
            continue
        skills = {}
        for column, skill in skill_columns.items():
            text = cells[column].strip() if column < len(cells) else ""
            status = STATUS_WORDS.get(text.lower())
            if status is None:
                warnings.append(f"{where}: {name} / {skill}: unknown status '{text}' ignored")
                status = SkillStatus.NONE
            skills[normalize(skill)] = status
        member = Staff(name=name, id=normalize(name), ral=_ral(cells, name), skills=skills)
        staff[member.id] = member
    check_unique(where, [s.name for s in staff.values()])
    return staff, warnings


def known_skills(table: Table) -> dict[str, str]:
    """Normalized skill name -> the Skills tab's own spelling of it."""
    return {normalize(skill): skill for skill in _skill_columns(table).values()}


def _skill_columns(table: Table) -> dict[int, str]:
    names, ranks = table[1], table[2]
    columns = {}
    for column in range(FIRST_SKILL_COLUMN, len(names)):
        name = names[column].strip()
        if not name:
            continue
        rank = ranks[column].strip() if column < len(ranks) else ""
        columns[column] = f"{name} {rank}".strip()
    return columns


def _ral(cells: list[str], name: str) -> int:
    text = cells[RAL_COLUMN].strip() if len(cells) > RAL_COLUMN else ""
    digits = text.split(" ")[0]
    if not digits.isdigit():
        raise LoadError(f"Skills: {name}: RAL '{text}' must start with a number")
    return int(digits)


def parse_position_skills(table: Table, known: Mapping[str, str]) -> PositionSkills:
    """The Positions tab, by normalized clinic name.

    `known` comes from `known_skills`. A cell naming a skill the Skills tab has no column
    for is a LoadError listing every such cell, so a typo is never read as "no skill".
    """
    rank_headers = ("1st", "2nd", "3rd")
    where = "Skills/Positions"
    rows = header_rows(table, ("Clinic_Name",) + rank_headers, where)
    result: PositionSkills = {}
    unknown = []
    for row in rows:
        clinic = row["Clinic_Name"]
        skills: list[str | None] = []
        for rank in rank_headers:
            text = row[rank]
            skill = normalize(text)
            if text and skill != ANY_SKILL and skill not in known:
                unknown.append(f"{clinic} {rank}: '{text}'")
            skills.append(skill or None)
        positions = tuple(skills[: len(POSITION_ROLES)])
        result[normalize(clinic)] = ClinicPositions(clinic, positions)
    if unknown:
        raise LoadError(
            f"{where}: the Skills tab has no column for these, so no one could be checked "
            "off on them:\n  " + "\n  ".join(unknown)
        )
    check_unique(where, [row["Clinic_Name"] for row in rows])
    return result


def trainers(staff: dict[str, Staff]) -> frozenset[str]:
    """Ids of staff who can supervise a scaffold on at least one skill."""
    return frozenset(
        s.id for s in staff.values() if any(status.can_scaffold for status in s.skills.values())
    )
