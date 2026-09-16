"""What the request table filters on: derived from each request, no Qt involved."""

from dataclasses import dataclass
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Choice
from puppet_strings.skedge.scope import scope
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
    try:
        copies = validate_request(request, dataset)
    except ast.SkedgeError as e:
        return Facets(_scope_of(request), frozenset(), frozenset(), frozenset(), str(e))
    staff: set[str] = set()
    activities: set[str] = set()
    dates: set[date] = set()
    for copy in copies:
        for statement in copy.statements:
            staff |= set(statement.across.items)
            dates |= set(statement.on.items)
            if isinstance(statement.target, Choice):
                activities |= set(statement.target.items)
    return Facets(_scope_of(request), frozenset(staff), frozenset(activities), frozenset(dates))


def _scope_of(request: Request) -> str:
    """Derive the persistence scope from the ON clause.

    season: no ON. session: ON date.session. day: one date. pin: a MUST_HAPPEN day for
    one staff member or category. week: anything else (ranges, offsets, weekday names).
    """
    try:
        scoped = scope(parse(request.skedge))
    except ast.SkedgeError:
        return "season"
    ons = [v.get(ast.On) for v in scoped.verbs if v.get(ast.On)]
    if not ons:
        return "season"
    expr = ons[0].selector.expr
    if isinstance(expr, ast.Ref) and expr.name == "session":
        return "session"
    single_day = isinstance(expr, ast.DateLiteral) or (
        isinstance(expr, ast.Ref) and expr.name == "target"
    )
    if not single_day:
        return "week"
    across = [v.get(ast.Across) for v in scoped.verbs if v.get(ast.Across)]
    one_person = across and isinstance(across[0].selector.expr, ast.Ref)
    if request.priority.hard and one_person and across[0].selector.quantifier is None:
        return "pin"
    return "day"
