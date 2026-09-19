"""Blocks: one row per time block.

Columns: block_id, start, end, day_types, program_type, categories. The last three are
comma-separated. A block exists on a day when the day runs one of its programmes and is one
of its kinds of day, so `weekday, weekend` is every day of a span and `first_day` is only
the day it starts.
"""

from puppet_strings.model import DAY_TYPES, PROGRAM_TYPES, Block
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_time, split_list

ALL_BLOCKS = "all"


def parse_blocks(table: Table) -> dict[str, Block]:
    """Blocks by id."""
    where = "Blocks"
    columns = ("block_id", "start", "end", "day_types", "program_type", "categories")
    rows = header_rows(table, columns, where)
    blocks = {}
    for row in rows:
        block_id = normalize(row["block_id"])
        cell = f"{where} row '{row['block_id']}'"
        block = Block(
            id=block_id,
            start=parse_time(row["start"], cell),
            end=parse_time(row["end"], cell),
            day_types=_kinds(row["day_types"], DAY_TYPES, "day_types", cell),
            program_types=_kinds(row["program_type"], PROGRAM_TYPES, "program_type", cell),
            categories=frozenset(normalize(c) for c in split_list(row["categories"]))
            | {ALL_BLOCKS},
        )
        if block.minutes <= 0:
            raise LoadError(f"{cell}: end must be after start")
        if block_id in blocks:
            raise LoadError(f"{cell}: duplicate block id")
        blocks[block_id] = block
    return blocks


def block_categories(blocks: dict[str, Block]) -> dict[str, frozenset[str]]:
    """Category id -> block ids, including the built-in `all`."""
    names = {c for b in blocks.values() for c in b.categories}
    return {c: frozenset(b.id for b in blocks.values() if c in b.categories) for c in names}


def _kinds(value: str, allowed: tuple[str, ...], column: str, where: str) -> frozenset[str]:
    """A comma-separated cell of one vocabulary, with a LoadError naming anything outside it."""
    kinds = frozenset(normalize(item) for item in split_list(value))
    unknown = sorted(kinds - set(allowed))
    if unknown:
        listed = ", ".join(a.replace("_", " ") for a in allowed)
        raise LoadError(f"{where}: {column} '{unknown[0]}' is not one of {listed}")
    if not kinds:
        raise LoadError(f"{where}: {column} is empty; it must name at least one")
    return kinds
