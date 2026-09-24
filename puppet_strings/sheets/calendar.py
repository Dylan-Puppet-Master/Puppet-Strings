"""Calendar: one row per span of days, with the programme it runs.

Columns: `name`, `start date`, `end date`, `program type`. A row covers every day from its
start to its end, so a fortnight is one row rather than fourteen.

The main season rows are numbered in sheet order, and that number is what
`dates.session_4` is named after; anything else is reached by its name, as
`dates.family_camp`. Weeks are not written down: a span's week 1 is its first seven
days, week 2 the next seven, which is why a row aligned to calendar weeks shows the week
labels you would expect down the side of the calendar pane.
"""

from datetime import date

from puppet_strings.model import (
    MAIN_SEASON,
    MAX_COUNTED,
    PROGRAM_TYPES,
    RESERVED_DATE_NAMES,
    CalendarDay,
    Span,
)
from puppet_strings.names import normalize
from puppet_strings.sheets.source import (
    MONTH_FIRST,
    LoadError,
    Table,
    header_rows,
    parse_date,
)

COLUMNS = ("name", "start date", "end date", "program type")


def parse_calendar(table: Table, order: str = MONTH_FIRST) -> tuple[Span, ...]:
    """The Calendar sheet's spans, in sheet order.

    `order` is how to read a numeric date whose day and month could be either way round;
    see `source.parse_date`. A column formatted as a date in Google Sheets reads back as
    whatever it displays, so this is the one thing about it that has to be declared.
    """
    where = "Calendar"
    rows = header_rows(table, COLUMNS, where)
    spans: list[Span] = []
    session = 0
    for row in rows:
        cell = f"{where} row '{row['name']}'"
        if not row["name"]:
            raise LoadError(f"{where}: a row has no name")
        program = normalize(row["program type"])
        if program not in PROGRAM_TYPES:
            allowed = ", ".join(p.replace("_", " ") for p in PROGRAM_TYPES)
            raise LoadError(f"{cell}: program type must be one of {allowed}")
        start = parse_date(row["start date"], f"{cell}: start date", order)
        end = parse_date(row["end date"], f"{cell}: end date", order)
        if end < start:
            raise LoadError(f"{cell}: end date {end} is before start date {start}")
        if program == MAIN_SEASON:
            session += 1
        spans.append(
            Span(
                name=row["name"],
                id=normalize(row["name"]),
                start=start,
                end=end,
                program_type=program,
                session=session if program == MAIN_SEASON else None,
            )
        )
    _check(spans, where)
    return tuple(spans)


def calendar_days(spans: tuple[Span, ...]) -> dict[date, CalendarDay]:
    """Every camp day, read off the spans that cover it."""
    days: dict[date, CalendarDay] = {}
    for span in spans:
        for day in span.dates:
            days[day] = span.day(day)
    return dict(sorted(days.items()))


def _check(spans: list[Span], where: str) -> None:
    """Names are unique, spans do not overlap, and nothing is counted past its name."""
    seen: dict[str, Span] = {}
    for span in spans:
        if span.id in seen:
            raise LoadError(f"{where}: two rows are both named '{span.name}'")
        seen[span.id] = span
    if len(seen) != len(spans):  # unreachable, but says what the ids are for
        raise LoadError(f"{where}: every row needs a name of its own")
    covered: dict[date, Span] = {}
    for span in spans:
        for day in span.dates:
            if day in covered:
                raise LoadError(
                    f"{where}: {day} is in both '{covered[day].name}' and '{span.name}'; "
                    "a day belongs to one row"
                )
            covered[day] = span
    for span in spans:
        if span.session is None and span.id in RESERVED_DATE_NAMES:
            raise LoadError(
                f"{where} row '{span.name}': 'dates.{span.id}' is already a name in Skedge; "
                "give the row another name"
            )
    sessions = [s for s in spans if s.session is not None]
    if len(sessions) > MAX_COUNTED:
        raise LoadError(f"{where}: at most {MAX_COUNTED} main season rows are supported")
    for span in spans:
        if span.weeks > MAX_COUNTED:
            raise LoadError(
                f"{where} row '{span.name}': runs to {span.weeks} weeks; "
                f"at most {MAX_COUNTED} are supported"
            )
