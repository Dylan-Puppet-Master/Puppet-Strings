"""Write a solved date into its own spreadsheet in the schedules tree.

A day's spreadsheet is `2027/Main Season/Session 1/Monday_1`, and `sheets.schedules` works
out that path from the Calendar. It holds the Offerings grid somebody fills in beforehand,
the assignment rows a later solve reads back, and the three views people read.
"""

from datetime import date

from puppet_strings.config import Config
from puppet_strings.model import Dataset, Span
from puppet_strings.publish.views import changes_view, clinic_view, report, staff_view
from puppet_strings.sheets.published import assignment_rows
from puppet_strings.sheets.schedules import (
    ROOT,
    day_tabs,
    day_title,
    offerings_template,
    span_path,
)
from puppet_strings.sheets.source import LoadError, Source
from puppet_strings.solver.result import Result

TEMPLATE = "clinic_schedule"  # the sheet whose Offerings grid a new day is started from


def day_sheet(source: Source, config: Config, span: Span, day: date) -> str:
    """The day's spreadsheet, made with its tabs if it is not there yet.

    A new one starts from the Clinic Schedule's Offerings grid, so the day opens with the
    usual clinics to prune rather than an empty sheet to build. One already there is
    returned untouched, grid and all.
    """
    path, title = span_path(span), day_title(span, day)
    found = source.documents(ROOT, path)
    if title in found:
        return found[title]
    sheet = source.create(ROOT, path, title, day_tabs(config))
    source.write(sheet, config.tabs["offerings"], _template(source, config, day))
    return sheet


def _template(source: Source, config: Config, day: date) -> list[list[str]]:
    """The grid a new day starts from, or an empty one when no Clinic Schedule is chosen.

    A missing template is not worth refusing to make the day over: the empty Offerings tab
    says so plainly, and the load warns that the day offers nothing.
    """
    try:
        return offerings_template(source.read(TEMPLATE, config.tabs["offerings"]), day)
    except LoadError:
        return []


def publish(source: Source, config: Config, dataset: Dataset, result: Result) -> None:
    """Write the day's assignments plus the Staff View, Clinic View and Report.

    Every tab goes in one write, and each view is dressed in two more. Google allows sixty
    write requests a minute per person; a day sent a tab and a bold row at a time spent most
    of that minute on one publish, and a second publish inside it was refused outright.
    """
    tabs = config.tabs
    sheet = day_sheet(source, config, dataset.this_span, dataset.target)
    staff = staff_view(dataset, result.assignments, config.remainder)
    clinics = clinic_view(dataset, result.assignments, config.remainder)
    written = {
        tabs["assignments"]: assignment_rows(result.assignments, dataset.staff, dataset.activities),
        tabs["staff_view"]: staff.rows,
        tabs["clinic_view"]: clinics.rows,
        tabs["report"]: report(result),
    }
    if dataset.baseline is not None:  # a same-day re-solve, so say what moved
        written[tabs["changes"]] = changes_view(dataset, result)
    source.write_many(sheet, written)
    source.style(sheet, tabs["staff_view"], staff)
    source.style(sheet, tabs["clinic_view"], clinics)


def is_published(source: Source, config: Config, dataset: Dataset) -> bool:
    """Whether the day has been solved, which is its assignments having rows.

    The spreadsheet existing is not enough: a load makes one with empty views for a
    day nobody has scheduled yet.
    """
    span = dataset.this_span
    found = source.documents(ROOT, span_path(span))
    title = day_title(span, dataset.target)
    if title not in found:
        return False
    return bool(source.read(found[title], config.tabs["assignments"]))
