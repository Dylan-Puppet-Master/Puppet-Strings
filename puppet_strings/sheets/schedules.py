"""Where a day's schedule lives in Drive, and what is in it.

One folder tree under the Puppet Strings folder chosen in the Configure pane, which is how
the Puppet Master keeps them. The root holds a folder per year:

    Puppet Strings/
      2027/
        Clinic_Data, Clinic_Schedule, Skills, Config   the season's reference sheets
        Main Season/
          Session 1/
            Staff Categories      one spreadsheet, for that session's staff
            Monday_1              one spreadsheet per day of the session
            Tuesday_1
            Monday_2              the second week's Monday

The year is the span's own year, the programme is its `program type` and the folder under
it is its `name`, all from the Calendar sheet, so nothing has to be written down twice. A
day is named for its weekday and which week of the span it falls in, because a fortnight
reaches Monday more than once.

Each day's spreadsheet holds the Offerings grid for that day and the three views a solve
writes, plus the assignment rows the views are drawn from. The views are for reading; the
assignments are what the solver reads back, because a published day is a fact that later
days are scheduled around and a grid of names cannot be turned back into who was on what
for how long.
"""

from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Span

ROOT = "root"  # the one folder the Configure pane asks for: the Puppet Strings folder

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

STAFF_CATEGORIES = "Staff Categories"  # the one spreadsheet in a span's folder that is not a day


def span_path(span: Span) -> tuple[str, ...]:
    """The folders a span's spreadsheets sit in, under the schedules root."""
    return (str(span.start.year), _programme(span.program_type), span.name)


def day_title(span: Span, day: date) -> str:
    """What a day's spreadsheet is called: `Monday_1` is the first week's Monday."""
    return f"{WEEKDAYS[day.weekday()]}_{span.week_of(day)}"


def day_tabs(config: Config) -> list[str]:
    """Every tab a day's spreadsheet is made with, the offerings grid first."""
    tabs = config.tabs
    return [
        tabs["offerings"],
        tabs["assignments"],
        tabs["staff_view"],
        tabs["clinic_view"],
        tabs["report"],
    ]


def offerings_template(table: list[list[str]], day: date) -> list[list[str]]:
    """The Clinic Schedule's Offerings grid, ready to be the starting point for one day.

    It is copied whole rather than emptied, because the same clinics run most days and
    pruning a grid is quicker than building one. Its weekday is set to the day's own, so a
    sheet started on a Wednesday does not warn about being read on a Thursday.
    """
    if not table:
        return []
    rows = [list(row) for row in table]
    for column, cell in enumerate(rows[0]):
        if cell.strip():
            rows[0][column] = WEEKDAYS[day.weekday()].upper()
            break
    return rows


def _programme(program_type: str) -> str:
    """`main_season` is the `Main Season` folder: the words the Calendar sheet used."""
    return program_type.replace("_", " ").title()
