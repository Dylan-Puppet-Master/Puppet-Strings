"""Metrics: an index tab listing each metric, plus one data tab per metric.

Index columns: metric, keys, scale_min, scale_max, and an optional default.
Data tab `metric_<name>`: one column per key (sheet names, not identifiers) and `value`.
"""

from collections.abc import Callable
from dataclasses import replace

from puppet_strings.model import Metric
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, split_list

KEY_FIELDS = ("staff", "activity", "role", "date", "block")
INDEX_COLUMNS = ("metric", "keys", "scale_min", "scale_max", "default")
TAB_PREFIX = "metric_"


def parse_metric_index(table: Table) -> list[Metric]:
    """One metric per index row, declared but with no values yet."""
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
        default = _number(row["default"], cell) if row.get("default") else low
        if not low <= default <= high:
            raise LoadError(f"{cell}: default {default} is outside {low}..{high}")
        index.append(
            Metric(
                name=normalize(row["metric"]),
                keys=keys,
                scale_min=low,
                scale_max=high,
                values={},
                default=default,
            )
        )
    return index


def parse_metric(metric: Metric, table: Table, to_id: Callable[[str, str], str]) -> Metric:
    """One metric's ratings. `to_id(field, sheet_value)` maps a key cell to its identifier."""
    where = f"Metrics/{TAB_PREFIX}{metric.name}"
    rows = header_rows(table, metric.keys + ("value",), where)
    values = {}
    for row in rows:
        key = tuple(to_id(field, row[field]) for field in metric.keys)
        cell = f"{where} row {list(key)}"
        value = _number(row["value"], cell)
        if not metric.scale_min <= value <= metric.scale_max:
            raise LoadError(
                f"{cell}: value {value} is outside {metric.scale_min}..{metric.scale_max}"
            )
        values[key] = value
    return replace(metric, values=values)


def _number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError as e:
        raise LoadError(f"{where}: '{text}' must be a number") from e
