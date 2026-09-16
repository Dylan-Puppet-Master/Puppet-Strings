"""Write a solved date to the Published Schedules spreadsheet."""

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.publish.views import clinic_view, report, staff_view
from puppet_strings.sheets.published import assignment_rows
from puppet_strings.sheets.source import Source
from puppet_strings.solver.result import Result

PUBLISHED = "published"


def publish(source: Source, config: Config, dataset: Dataset, result: Result) -> None:
    """Write the date's assignment tab plus the Staff View, Clinic View and Report tabs."""
    tab = dataset.target.isoformat()
    source.write(
        PUBLISHED, tab, assignment_rows(result.assignments, dataset.staff, dataset.activities)
    )
    view = staff_view(dataset, result.assignments, config.remainder)
    source.write(PUBLISHED, config.tabs["staff_view"], view)
    source.write(PUBLISHED, config.tabs["clinic_view"], clinic_view(dataset, result.assignments))
    source.write(PUBLISHED, config.tabs["report"], report(result))


def is_published(source: Source, dataset: Dataset) -> bool:
    """Whether the target date already has a tab."""
    return dataset.target.isoformat() in source.tabs(PUBLISHED)
