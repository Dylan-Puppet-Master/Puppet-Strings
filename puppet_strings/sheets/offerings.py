"""Offerings: the grid the Puppet Master fills in with tomorrow's clinics.

Row 1 holds the weekday. Row 2 holds a block heading ("Clinic 1") above each group of
columns. Below, a column lists category headings in capitals and clinic names; other
columns are lookups and are ignored. Everything below a "Cancelled" row is ignored.
A "(DBL)" clinic listed in two adjacent clinic blocks is one instance spanning both.
"""

from collections.abc import Mapping

from puppet_strings.model import Activity, Offering
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table

WEEKDAY_ROW = 0
HEADER_ROW = 1
CANCELLED = "cancelled"


def parse_offerings(
    table: Table, activities: Mapping[str, Activity], block_ids: set[str], weekday: str
) -> tuple[tuple[Offering, ...], list[str]]:
    """Offerings for the target date, plus warnings.

    `weekday` is the target date's day name, checked against row 1.
    """
    where = "Offerings"
    if len(table) <= HEADER_ROW:
        raise LoadError(f"{where}: expected a weekday row and a block heading row")
    warnings = []
    sheet_weekday = next((c.strip() for c in table[WEEKDAY_ROW] if c.strip()), "")
    if sheet_weekday.lower() != weekday.lower():
        warnings.append(f"{where}: tab says {sheet_weekday} but the target date is a {weekday}")
    columns = _block_columns(table[HEADER_ROW], block_ids, where)
    by_name = {a.name: a for a in activities.values()}
    categories = {a.category for a in activities.values()}
    listed: list[tuple[str, str]] = []  # (block id, activity id) in column order
    for column, block in columns:
        for cells in table[HEADER_ROW + 1 :]:
            text = cells[column].strip() if column < len(cells) else ""
            if text.lower() == CANCELLED:
                break
            if not text or text.isdigit() or normalize(text) in categories:
                continue
            if text not in by_name:
                raise LoadError(f"{where}: '{text}' under {block} is not a clinic in Clinic_Data")
            listed.append((block, by_name[text].id))
    return _merge_doubles(listed, activities, [b for _, b in columns], where), warnings


def _block_columns(header: list[str], block_ids: set[str], where: str) -> list[tuple[int, str]]:
    columns = [(i, normalize(c)) for i, c in enumerate(header) if normalize(c) in block_ids]
    if not columns:
        raise LoadError(f"{where}: no block heading in row 2 matches a block id")
    return columns


def _merge_doubles(
    listed: list[tuple[str, str]],
    activities: Mapping[str, Activity],
    block_order: list[str],
    where: str,
) -> tuple[Offering, ...]:
    offerings = []
    pending: dict[str, str] = {}  # double activity id -> first block awaiting its pair
    for block, activity_id in listed:
        if not activities[activity_id].double:
            offerings.append(Offering(activity_id, (block,)))
            continue
        if activity_id not in pending:
            pending[activity_id] = block
            continue
        first = pending.pop(activity_id)
        name = activities[activity_id].name
        if block_order.index(block) != block_order.index(first) + 1:
            raise LoadError(f"{where}: {name} in {first} and {block} are not adjacent")
        offerings.append(Offering(activity_id, (first, block)))
    for activity_id, block in pending.items():
        name = activities[activity_id].name
        raise LoadError(f"{where}: {name} is only in {block}; (DBL) needs two adjacent blocks")
    return tuple(offerings)
