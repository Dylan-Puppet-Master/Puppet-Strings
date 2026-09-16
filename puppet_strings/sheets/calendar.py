"""Calendar: one row per camp day with its session and day type."""

from datetime import date

from puppet_strings.model import CalendarDay
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows


def parse_calendar(table: Table) -> dict[date, CalendarDay]:
    """Calendar days by date."""
    where = "Calendar"
    rows = header_rows(table, ("date", "session", "day_type"), where)
    days = {}
    for row in rows:
        day = parse_date(row["date"], f"{where} row '{row['date']}'")
        if day in days:
            raise LoadError(f"{where}: {day} appears twice")
        days[day] = CalendarDay(
            date=day, session=normalize(row["session"]), day_type=normalize(row["day_type"])
        )
    return days


def parse_date(text: str, where: str) -> date:
    """An ISO date cell."""
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise LoadError(f"{where}: date '{text}' must be YYYY-MM-DD") from e
