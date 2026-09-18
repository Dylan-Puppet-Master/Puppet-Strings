"""What the request table filters on: derived from each request, no Qt involved."""

from dataclasses import dataclass
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Choice, Requirement
from puppet_strings.skedge.validate import validate_request

SCOPES = ("season", "session", "week", "day", "pin")


@dataclass(frozen=True)
class Facets:
    """Everything the filters need to know about one request."""

    scope: str
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
    try:
        declaration = parse(request.skedge)
        copies = validate_request(request, dataset)
    except ast.SkedgeError as e:
        return Facets("season", frozenset(), frozenset(), frozenset(), str(e))
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
    scope = _scope_of(declaration, request, dataset, dates)
    return Facets(scope, frozenset(staff), frozenset(activities), frozenset(dates))


def _dated(declaration: ast.Declaration) -> bool:
    """Whether the first statement says which dates it is about."""
    part = _subject(declaration)
    return part is not None and ast.clause(part.clauses, ast.On) is not None


def _subject(declaration: ast.Declaration):
    """The first statement's pattern, which is what the table describes the request by."""
    statements = declaration.statements
    if not statements:
        return None
    first = statements[0]
    return first if isinstance(first, ast.Requirement) else first.pattern


def _scope_of(
    declaration: ast.Declaration, request: Request, dataset: Dataset, dates: set[date]
) -> str:
    """How long a request reaches, from the dates it resolved to.

    season: every camp day. session: exactly one session's days. day: one day, or `pin`
    when that day is pinned on one person and must happen. week: anything in between.
    """
    if not dates or dates == set(dataset.calendar):
        return "season"
    if any(dates == set(days) for days in dataset.sessions.values()):
        return "session"
    if len(dates) > 1:
        return "week"
    return "pin" if _is_pin(declaration, request) else "day"


def _is_pin(declaration: ast.Declaration, request: Request) -> bool:
    """A must-happen day for one named person: the strongest thing a request can say."""
    part = _subject(declaration)
    if not isinstance(part, ast.Requirement) or not request.priority.hard:
        return False
    return isinstance(part.who.expr, ast.Ref) and part.who.quantifier is None
