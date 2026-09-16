"""Blocks: one row per time block.

Columns: block_id, start, end, day_types (comma-separated), categories (comma-separated).
"""

from datetime import time

from puppet_strings.model import Block
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, split_list

ANY_BLOCK = "any"


def parse_blocks(table: Table) -> dict[str, Block]:
    """Blocks by id."""
    where = "Blocks"
    rows = header_rows(table, ("block_id", "start", "end", "day_types", "categories"), where)
    blocks = {}
    for row in rows:
        block_id = normalize(row["block_id"])
        cell = f"{where} row '{row['block_id']}'"
        block = Block(
            id=block_id,
            start=_time(row["start"], cell),
            end=_time(row["end"], cell),
            day_types=frozenset(normalize(t) for t in split_list(row["day_types"])),
            categories=frozenset(normalize(c) for c in split_list(row["categories"])) | {ANY_BLOCK},
        )
        if block.minutes <= 0:
            raise LoadError(f"{cell}: end must be after start")
        if block_id in blocks:
            raise LoadError(f"{cell}: duplicate block id")
        blocks[block_id] = block
    return blocks


def block_categories(blocks: dict[str, Block]) -> dict[str, frozenset[str]]:
    """Category id -> block ids, including the built-in `any`."""
    names = {c for b in blocks.values() for c in b.categories}
    return {c: frozenset(b.id for b in blocks.values() if c in b.categories) for c in names}


def _time(text: str, where: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError as e:
        raise LoadError(f"{where}: time '{text}' must be HH:MM") from e
