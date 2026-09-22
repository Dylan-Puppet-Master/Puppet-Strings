"""Mappings: an index tab listing each mapping, plus one data tab per mapping.

Index columns: mapping, keys, values, and scale_min, scale_max and default, which a
mapping may leave blank where they do not apply. `keys` is a comma-separated list of
Skedge sets, one per key column; `values` is a Skedge set, or `numeric`.

Data tab `mapping_<name>`: `key1`, `key2`, ... one per key, and `value`, all written as
the other sheets write them (names, not identifiers).

A mapping is read in two steps. Its tabs are parsed while the rest of the day is, into
identifiers; once the day is built, `check_mappings` asks whether every row names what its
keys and values say it may, which takes the day's own categories to answer.
"""

from dataclasses import replace
from datetime import date

from puppet_strings.model import NUMERIC, Dataset, MappingTable
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_date, split_list
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.namespaces import DATES
from puppet_strings.skedge.resolve import default_choice, domain, domain_namespace, judged

INDEX = "Mappings"
INDEX_COLUMNS = ("mapping", "keys", "values", "scale_min", "scale_max", "default")
REQUIRED = ("mapping", "keys", "values")
TAB_PREFIX = "mapping_"
VALUE = "value"


def key_columns(count: int) -> tuple[str, ...]:
    """The key columns of a data tab: `key1`, `key2`, ..."""
    return tuple(f"key{i}" for i in range(1, count + 1))


def parse_mapping_index(table: Table) -> list[MappingTable]:
    """One mapping per index row, declared but with no rows yet."""
    index = []
    for row in header_rows(table, REQUIRED, INDEX):
        cell = f"{INDEX} row '{row['mapping']}'"
        keys = tuple(split_list(row["keys"]))
        if not keys:
            raise LoadError(f"{cell}: keys needs at least one set, such as staff.counselor")
        values = row["values"].strip()
        for text in keys + (() if values.lower() == NUMERIC else (values,)):
            _namespace(text, cell)
        if values.lower() == NUMERIC:
            index.append(_numeric(row, keys, cell))
        else:
            index.append(_named(row, keys, values, cell))
    return index


def _numeric(row: dict[str, str], keys: tuple[str, ...], cell: str) -> MappingTable:
    if not row.get("scale_min") or not row.get("scale_max"):
        raise LoadError(f"{cell}: a numeric mapping needs scale_min and scale_max")
    low, high = _number(row["scale_min"], cell), _number(row["scale_max"], cell)
    if high <= low:
        raise LoadError(f"{cell}: scale_max must exceed scale_min")
    default = _number(row["default"], cell) if row.get("default") else low
    if not low <= default <= high:
        raise LoadError(f"{cell}: default {default:g} is outside {low:g}..{high:g}")
    return MappingTable(normalize(row["mapping"]), keys, NUMERIC, {}, low, high, default)


def _named(row: dict[str, str], keys: tuple[str, ...], values: str, cell: str) -> MappingTable:
    if row.get("scale_min") or row.get("scale_max"):
        raise LoadError(f"{cell}: only a numeric mapping has a scale; its values are {values}")
    default = row.get("default") or None
    return MappingTable(normalize(row["mapping"]), keys, values, {}, default=default)


def parse_mapping(mapping: MappingTable, table: Table, date_order: str) -> MappingTable:
    """One mapping's rows, as identifiers. Whether they belong is `check_mappings`' to say."""
    where = f"{INDEX}/{TAB_PREFIX}{mapping.name}"
    columns = key_columns(len(mapping.keys))
    namespaces = [domain_namespace(text) for text in mapping.keys]
    rows: dict[tuple[str, ...], float | str] = {}
    for row in header_rows(table, columns + (VALUE,), where):
        key = tuple(
            _identifier(row[column], namespace, where, date_order)
            for column, namespace in zip(columns, namespaces, strict=True)
        )
        cell = f"{where} row {list(key)}"
        if key in rows:
            raise LoadError(f"{cell}: written twice; a key has one value")
        rows[key] = _value(mapping, row[VALUE], cell, date_order)
    return replace(mapping, rows=rows)


def _value(mapping: MappingTable, text: str, cell: str, date_order: str) -> float | str:
    if not mapping.numeric:
        return _identifier(text, domain_namespace(mapping.values), cell, date_order)
    value = _number(text, cell)
    if not mapping.scale_min <= value <= mapping.scale_max:
        raise LoadError(
            f"{cell}: value {value:g} is outside {mapping.scale_min:g}..{mapping.scale_max:g}"
        )
    return value


def check_mappings(dataset: Dataset) -> None:
    """Raise LoadError unless every mapping's rows and default name what it says they may.

    This is where a mapping is checked the way a request is: a key cell naming someone who
    is not a counselor, a buddy who is a counselor themselves, a default reaching outside
    the values. Staff who are not working today are in no category today, so whether they
    belong to one cannot be told and is not asked.
    """
    for mapping in dataset.mappings.values():
        where = f"{INDEX}/{TAB_PREFIX}{mapping.name}"
        sets = [_domain(text, dataset, f"{INDEX} row '{mapping.name}'") for text in mapping.keys]
        gives = None if mapping.numeric else _domain(mapping.values, dataset, where)
        for key, value in mapping.rows.items():
            cell = f"{where} row {list(key)}"
            for item, (namespace, items), text in zip(key, sets, mapping.keys, strict=True):
                _belongs(item, namespace, items, text, dataset, cell)
            if gives is not None:
                _belongs(value, *gives, mapping.values, dataset, cell)
        if gives is not None and mapping.default is not None:
            _check_default(mapping, gives, dataset)


def _check_default(mapping: MappingTable, gives: tuple, dataset: Dataset) -> None:
    cell = f"{INDEX} row '{mapping.name}'"
    try:
        namespace, items = default_choice(mapping.default, dataset)
    except SkedgeError as e:
        raise LoadError(f"{cell}: default '{mapping.default}': {e.message}") from e
    if namespace != gives[0]:
        raise LoadError(
            f"{cell}: default '{mapping.default}' names {namespace}, but the values are {gives[0]}"
        )
    outside = sorted(str(i) for i in items - gives[1] if judged(i, namespace, dataset))
    if outside:
        raise LoadError(
            f"{cell}: default '{mapping.default}' reaches '{outside[0]}', which is not in "
            f"{mapping.values}"
        )


def _belongs(item, namespace, items, text, dataset, cell) -> None:
    """A key or value cell must name something, and something its set holds."""
    found = date.fromisoformat(item) if namespace == DATES else item
    if found in items:
        return
    if found not in domain(namespace, dataset)[1]:
        raise LoadError(f"{cell}: '{item}' is not a name in {namespace}")
    if judged(found, namespace, dataset):
        raise LoadError(f"{cell}: '{item}' is not in {text}")


def _domain(text: str, dataset: Dataset, cell: str) -> tuple:
    try:
        return domain(text, dataset)
    except SkedgeError as e:
        raise LoadError(f"{cell}: '{text}': {e.message}") from e


def _namespace(text: str, cell: str) -> str:
    try:
        return domain_namespace(text)
    except SkedgeError as e:
        raise LoadError(f"{cell}: {e.message}") from e


def _identifier(text: str, namespace: str, where: str, date_order: str) -> str:
    """A cell as the other sheets write it, as the identifier Skedge knows it by."""
    if namespace == DATES:
        return parse_date(text, where, date_order).isoformat()
    return normalize(text)


def _number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError as e:
        raise LoadError(f"{where}: '{text}' must be a number") from e
