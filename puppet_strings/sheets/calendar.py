"""Calendar: one row per camp day with its session, its week of that session, and day type."""

from datetime import date

from puppet_strings.model import MAX_COUNTED, CalendarDay
from puppet_strings.names import normalize
from puppet_strings.sheets.source import LoadError, Table, header_rows, parse_int

COLUMNS = ("date", "session", "week", "day_type")


def parse_calendar(table: Table) -> dict[date, CalendarDay]:
    """Calendar days by date. Session and week are the numbers Skedge counts dates by."""
    where = "Calendar"
    rows = header_rows(table, COLUMNS, where)
    days = {}
    for row in rows:
        cell = f"{where} row '{row['date']}'"
        day = parse_date(row["date"], cell)
        if day in days:
            raise LoadError(f"{where}: {day} appears twice")
        days[day] = CalendarDay(
            date=day,
            session=_counted(row["session"], "session", cell),
            week=_counted(row["week"], "week", cell),
            day_type=normalize(row["day_type"]),
        )
    _check_weeks(days, where)
    return days


def parse_date(text: str, where: str) -> date:
    """An ISO date cell."""
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise LoadError(f"{where}: date '{text}' must be YYYY-MM-DD") from e


def _counted(text: str, field: str, where: str) -> int:
    """A session or week number: what `dates.session.four.second_week` is named after."""
    number = parse_int(text, f"{where}: {field}")
    if not 1 <= number <= MAX_COUNTED:
        raise LoadError(f"{where}: {field} must be between 1 and {MAX_COUNTED}, not {number}")
    return number


def _check_weeks(days: dict[date, CalendarDay], where: str) -> None:
    """A session's weeks run 1, 2, 3 … with none skipped, so every week has a name."""
    weeks: dict[int, set[int]] = {}
    for day in days.values():
        weeks.setdefault(day.session, set()).add(day.week)
    for session, numbers in sorted(weeks.items()):
        expected = set(range(1, max(numbers) + 1))
        missing = sorted(expected - numbers)
        if missing:
            raise LoadError(
                f"{where}: session {session} has a week {missing[0]} with no days; "
                "number a session's weeks 1, 2, 3 … with none skipped"
            )
