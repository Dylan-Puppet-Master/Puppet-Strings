"""Staff Categories: one column per category, members listed below the heading."""

from puppet_strings.model import Staff
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table

SKIPPED_HEADINGS = {"", "etc."}


def parse_staff_categories(table: Table, staff: dict[str, Staff]) -> dict[str, frozenset[str]]:
    """Category id -> member ids. Every member must be on the Skills sheet."""
    where = "Staff Categories"
    if not table:
        raise LoadError(f"{where}: empty tab")
    by_name = {s.name: s.id for s in staff.values()}
    categories: dict[str, frozenset[str]] = {}
    for column, heading in enumerate(table[0]):
        heading = heading.strip()
        if heading in SKIPPED_HEADINGS:
            continue
        members = set()
        for cells in table[1:]:
            name = cells[column].strip() if column < len(cells) else ""
            if not name:
                continue
            if name not in by_name:
                raise LoadError(f"{where}: '{name}' under '{heading}' is not on the Skills sheet")
            members.add(by_name[name])
        category = normalize(heading)
        if category in categories:
            raise LoadError(f"{where}: category '{heading}' appears twice")
        categories[category] = frozenset(members)
    return categories
