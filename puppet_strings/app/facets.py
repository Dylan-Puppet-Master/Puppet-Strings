"""What the request table filters on: derived from each request, no Qt involved."""

from dataclasses import dataclass
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Choice, Requirement
from puppet_strings.skedge.validate import validate_request


@dataclass(frozen=True)
class Facets:
    """Everything the filters need to know about one request."""

    staff: frozenset[str]
    activities: frozenset[str]
    dates: frozenset[date]
    error: str | None = None

    @property
    def valid(self) -> bool:
        """Whether the request passed validation."""
        return self.error is None

    def covers(self, day: date) -> bool:
        """Whether the request has anything to say about a date.

        A request that does not cover the date being scheduled is still a real request; it
        just does nothing today, which is what the editor warns about before saving it.
        """
        return day in self.dates


def facets(request: Request, dataset: Dataset) -> Facets:
    """Derive filter facets; an invalid request gets empty facets and its error text."""
    return resolve_request(request, dataset)[0]


def resolve_request(request: Request, dataset: Dataset) -> tuple[Facets, tuple]:
    """The request's facets and the copies it resolved to, from one pass of the validator.

    The copies are what the conflict finder reads, and resolving is the expensive part of
    reading a request, so the two are done together.
    """
    try:
        declaration = parse(request.skedge)
        copies = validate_request(request, dataset)
    except ast.SkedgeError as e:
        return Facets(frozenset(), frozenset(), frozenset(), str(e)), ()
    staff: set[str] = set()
    activities: set[str] = set()
    dates: set[date] = set()
    for copy in copies:
        for statement in copy.statements:
            part = statement if isinstance(statement, Requirement) else statement.pattern
            staff |= set(part.who.items)
            dates |= set(part.on.items)
            if isinstance(part.what, Choice):
                activities |= set(part.what.items)
    if not _dated(declaration):  # no ON: the request applies on every day scheduled
        dates = set(dataset.calendar)
    return Facets(frozenset(staff), frozenset(activities), frozenset(dates)), copies


def _dated(declaration: ast.Declaration) -> bool:
    """Whether the first statement says which dates it is about."""
    statements = declaration.statements
    if not statements:
        return False
    first = statements[0]
    part = first if isinstance(first, ast.Requirement) else first.pattern
    return ast.clause(part.clauses, ast.On) is not None
