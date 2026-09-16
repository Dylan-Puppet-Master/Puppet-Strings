"""Skills: who is checked off on what, and which skill each clinic position needs.

Main tab layout:
  row 1: skill group headings (ignored)
  row 2: skill name; blank marks a date column, which is skipped
  row 3: rank ("1st", "2nd", "1st CW") or blank
  rows 4+: staff name, RAL, a count (ignored), then one status cell per column

A skill's full name is row 2 plus row 3, e.g. "Canopy Tour 1st", matching the
Positions tab, which maps Clinic_Name to the skill of its 1st, 2nd and 3rd position.
"""

from puppet_strings.model import POSITION_ROLES, SkillStatus, Staff
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
            skills[skill] = status
        member = Staff(name=name, id=normalize(name), ral=_ral(cells, name), skills=skills)
        staff[member.id] = member
    check_unique(where, [s.name for s in staff.values()])
    return staff, warnings


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


def parse_position_skills(table: Table) -> dict[str, tuple[str | None, ...]]:
    """Clinic name -> skill required by each position, in order. Blank means any staff."""
    rank_headers = ("1st", "2nd", "3rd")
    rows = header_rows(table, ("Clinic_Name",) + rank_headers, "Skills/Positions")
    result = {}
    for row in rows:
        skills = tuple(row[rank] or None for rank in rank_headers)
        result[row["Clinic_Name"]] = skills[: len(POSITION_ROLES)]
    return result


def trainers(staff: dict[str, Staff]) -> frozenset[str]:
    """Ids of staff who can supervise a scaffold on at least one skill."""
    return frozenset(
        s.id for s in staff.values() if any(status.can_scaffold for status in s.skills.values())
    )
