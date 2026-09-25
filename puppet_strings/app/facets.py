"""What the request table filters on: derived from each request, no Qt involved."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.namespaces import DATES
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Choice, Exclusion, Requirement
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
            if isinstance(statement, Exclusion):
                staff |= set(statement.who.items)
                dates |= set(statement.on.items)
                continue
            part = statement if isinstance(statement, Requirement) else statement.pattern
            staff |= set(part.who.items)
            dates |= set(part.on.items)
            if isinstance(part.what, Choice):
                activities |= set(part.what.items)
    if not _dated(declaration):  # no ON: the request applies on every day scheduled
        dates = set(dataset.calendar)
    return Facets(frozenset(staff), frozenset(activities), frozenset(dates)), copies


def named_dates(request: Request, dataset: Dataset, copies=None) -> frozenset[date]:
    """The dates a request's ON clauses tie it to, which its scope has to hold.

    None for a request without ON, which is about whatever day it is read on. None too
    for one whose ON moves with the date being scheduled, `ON dates.target` or
    `dates.target - 6d .. dates.target`: it asks the same of every day, so any scope holds
    it. And none for one that does not validate. `copies`, if the request has just been
    resolved, saves resolving it again.
    """
    try:
        declaration = parse(request.skedge)
        if copies is None:
            copies = validate_request(request, dataset)
    except ast.SkedgeError:
        return frozenset()
    ons = list(_found(declaration, ast.On))
    if not ons or any(next(_found(on, ast.Ref, _follows_target), None) for on in ons):
        return frozenset()
    dates: set[date] = set()
    for copy in copies:
        for statement in copy.statements:
            if isinstance(statement, Exclusion):
                dates |= set(statement.on.items)
                continue
            part = statement if isinstance(statement, Requirement) else statement.pattern
            dates |= set(part.on.items)
    return frozenset(dates)


def written_dates(days) -> str:
    """A few dates as the window writes them: `Thu Sep 24`, `Mon Sep 14, Tue Sep 15 and 3 more`."""
    days = sorted(days)
    shown = ", ".join(f"{d:%a %b} {d.day}" for d in days[:3])
    return shown + (f" and {len(days) - 3} more" if len(days) > 3 else "")


def _follows_target(ref: ast.Ref) -> bool:
    """`dates.target`, `dates.session_target`, `week_target`: names that move with the date."""
    return ref.namespace == DATES and "target" in ref.name


def _found(node, kind: type, wanted=lambda _: True):
    """Every node of a kind anywhere under `node` in a Skedge tree, that `wanted` accepts."""
    if isinstance(node, kind) and wanted(node):
        yield node
    if is_dataclass(node) and not isinstance(node, type):
        for f in fields(node):
            yield from _found(getattr(node, f.name), kind, wanted)
    elif isinstance(node, tuple | list):
        for item in node:
            yield from _found(item, kind, wanted)


def _dated(declaration: ast.Declaration) -> bool:
    """Whether the first statement says which dates it is about."""
    statements = declaration.statements
    if not statements:
        return False
    first = statements[0]
    part = first if isinstance(first, ast.Requirement | ast.Exclude) else first.pattern
    return ast.clause(part.clauses, ast.On) is not None
