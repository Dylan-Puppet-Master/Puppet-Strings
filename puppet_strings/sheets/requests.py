"""Requests: one row per request, one column per field."""

from puppet_strings.model import WRITABLE_PRIORITIES, Priority, Request
from puppet_strings.sheets.calendar import parse_date
from puppet_strings.sheets.source import LoadError, Table, header_rows, split_list

COLUMNS = ("id", "description", "skedge", "priority", "weight", "tags", "created")
REQUIRED = tuple(c for c in COLUMNS if c != "tags")


def parse_requests(table: Table) -> tuple[Request, ...]:
    """Requests in sheet order. Checks fields, not Skedge (see skedge.validate)."""
    where = "Requests"
    rows = header_rows(table, REQUIRED, where)
    requests = []
    ids = set()
    for row in rows:
        cell = f"{where} row '{row['id']}'"
        if not row["id"]:
            raise LoadError(f"{where}: a row has no id")
        if row["id"] in ids:
            raise LoadError(f"{cell}: duplicate id")
        ids.add(row["id"])
        try:
            priority = Priority(row["priority"])
        except ValueError as e:
            allowed = [p.value for p in WRITABLE_PRIORITIES]
            raise LoadError(f"{cell}: priority must be one of {allowed}") from e
        if priority not in WRITABLE_PRIORITIES:
            raise LoadError(f"{cell}: {priority.value} is the solver's own, not a priority to set")
        weight = _weight(row["weight"], priority, cell)
        created = parse_date(row["created"], cell) if row["created"] else None
        requests.append(
            Request(
                id=row["id"],
                description=row["description"],
                skedge=row["skedge"],
                priority=priority,
                weight=weight,
                tags=tuple(split_list(row.get("tags", ""))),
                created=created,
            )
        )
    return tuple(requests)


def request_rows(requests: tuple[Request, ...]) -> Table:
    """Requests as a table with a header row, for writing back."""
    rows: Table = [list(COLUMNS)]
    for r in requests:
        weight = "" if r.priority.hard else _format_weight(r.weight)
        created = r.created.isoformat() if r.created else ""
        tags = ", ".join(r.tags)
        rows.append([r.id, r.description, r.skedge, r.priority.value, weight, tags, created])
    return rows


def _weight(text: str, priority: Priority, where: str) -> float:
    if not text:
        return 1.0
    if priority.hard:
        raise LoadError(f"{where}: weight is not allowed with MUST_HAPPEN")
    try:
        weight = float(text)
    except ValueError as e:
        raise LoadError(f"{where}: weight '{text}' must be a number") from e
    if weight <= 0:
        raise LoadError(f"{where}: weight must be positive")
    return weight


def _format_weight(weight: float) -> str:
    return str(int(weight)) if weight == int(weight) else str(weight)
