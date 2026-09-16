"""Metrics: an index tab listing each metric, plus one data tab per metric.

Index columns: metric, keys, scale_min, scale_max.
Data tab `metric_<name>`: one column per key (sheet names, not identifiers) and `value`.
"""

from collections.abc import Callable

from puppet_strings.model import Metric
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, split_list

KEY_FIELDS = ("staff", "activity", "role", "date", "block")
TAB_PREFIX = "metric_"


def parse_metric_index(table: Table) -> list[tuple[str, tuple[str, ...], float, float]]:
    """(name, keys, scale_min, scale_max) per index row."""
    where = "Metrics"
    rows = header_rows(table, ("metric", "keys", "scale_min", "scale_max"), where)
    index = []
    for row in rows:
        cell = f"{where} row '{row['metric']}'"
        keys = tuple(k.lower() for k in split_list(row["keys"]))
        bad = [k for k in keys if k not in KEY_FIELDS]
        if bad or not keys:
            raise LoadError(f"{cell}: keys must be some of {KEY_FIELDS}")
        low, high = _number(row["scale_min"], cell), _number(row["scale_max"], cell)
        if high <= low:
            raise LoadError(f"{cell}: scale_max must exceed scale_min")
        index.append((normalize(row["metric"]), keys, low, high))
    return index


def parse_metric(
    name: str,
    keys: tuple[str, ...],
    scale_min: float,
    scale_max: float,
    table: Table,
    to_id: Callable[[str, str], str],
) -> Metric:
    """One metric's data. `to_id(field, sheet_value)` maps a key cell to its identifier."""
    where = f"Metrics/{TAB_PREFIX}{name}"
    rows = header_rows(table, keys + ("value",), where)
    values = {}
    for row in rows:
        key = tuple(to_id(field, row[field]) for field in keys)
        cell = f"{where} row {list(key)}"
        value = _number(row["value"], cell)
        if not scale_min <= value <= scale_max:
            raise LoadError(f"{cell}: value {value} is outside {scale_min}..{scale_max}")
        values[key] = value
    return Metric(name=name, keys=keys, scale_min=scale_min, scale_max=scale_max, values=values)


def _number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError as e:
        raise LoadError(f"{where}: '{text}' must be a number") from e
