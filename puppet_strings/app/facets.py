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


def facets(request: Request, dataset: Dataset) -> Facets:
    """Derive filter facets; an invalid request gets empty facets and its error text."""
    scope = _scope_of(request)
    try:
        copies = validate_request(request, dataset)
    except ast.SkedgeError as e:
        return Facets(scope, frozenset(), frozenset(), frozenset(), str(e))
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
    if scope == "season":  # no ON: the request applies on every day scheduled
        dates = set(dataset.calendar)
    return Facets(scope, frozenset(staff), frozenset(activities), frozenset(dates))


def _scope_of(request: Request) -> str:
    """Derive the persistence scope from the first statement's ON clause.

    season: no ON, or `date.season.all`. session: `date.session.all`. day: one date. pin: a
    MUST_HAPPEN day for one staff member. week: anything else.
    """
    try:
        statements = parse(request.skedge).statements
    except ast.SkedgeError:
        return "season"
    if not statements:
        return "season"
    first = statements[0]
    part = first if isinstance(first, ast.Requirement) else first.pattern
    on = ast.clause(part.clauses, ast.On)
    if on is None:
        return "season"
    expr = on.selector.expr
    if isinstance(expr, ast.Ref) and expr.name == "season.all":
        return "season"
    if isinstance(expr, ast.Ref) and expr.name == "session.all":
        return "session"
    single_day = isinstance(expr, ast.DateLiteral) or (
        isinstance(expr, ast.Ref) and expr.name == "target"
    )
    if not single_day:
        return "week"
    one_person = isinstance(part.who.expr, ast.Ref) and part.who.quantifier is None
    if request.priority.hard and one_person and isinstance(part, ast.Requirement):
        return "pin"
    return "day"
