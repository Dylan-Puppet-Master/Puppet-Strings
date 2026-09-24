"""Every check a request must pass before the solver sees it.

The parser rejects what the grammar cannot say. This module checks the rest of the
declaration's shape: statements, clauses, labels and variables. Names are checked by the
resolver, which needs the dataset.
"""

from puppet_strings.model import Dataset, Request
from puppet_strings.skedge import ast
from puppet_strings.skedge.parser import parse
from puppet_strings.skedge.resolve import Resolved, is_prefer, resolve

CLAUSE_NAMES = {
    ast.During: "DURING",
    ast.On: "ON",
    ast.AsRole: "AS_ROLE",
    ast.For: "FOR",
    ast.With: "WITH",
    ast.Without: "WITHOUT",
}


def validate_request(request: Request, dataset: Dataset) -> tuple[Resolved, ...]:
    """Parse, check, and resolve one request. Raises SkedgeError with line and column."""
    if request.weight <= 0:
        raise ast.SkedgeError("weight must be positive", 1, 1)
    if request.priority.hard and request.weight != 1:
        raise ast.SkedgeError("weight is not allowed with MUST_HAPPEN", 1, 1)
    if request.requester and request.requester not in dataset.staff:
        raise ast.SkedgeError(f"unknown requester '{request.requester}'", 1, 1)
    declaration = parse(request.skedge)
    check(declaration, hard=request.priority.hard)
    return resolve(declaration, dataset)


def check(declaration: ast.Declaration, hard: bool) -> None:
    """The rules about a declaration's shape that need no dataset."""
    statements = declaration.statements
    if not statements:
        raise ast.SkedgeError("a declaration needs at least one statement", 1, 1)
    if declaration.exclusions:
        _check_exclusions(declaration, hard)
        return
    conditions = declaration.conditions
    if len(conditions) > 1:
        raise _error("only one IF or UNLESS per declaration", conditions[1].pos)
    prefers = [s for s in statements if is_prefer(s)]
    if prefers and hard:
        raise _error(
            "PREFER needs a priority it can be weighed at, so not MUST_HAPPEN", prefers[0].pos
        )
    for line in declaration.lines:
        _check_line(line)
    _check_labels(declaration)
    _check_variables(declaration)


def _check_exclusions(declaration: ast.Declaration, hard: bool) -> None:
    """An EXCLUDE says who is not at camp, which is a fact rather than something to want.

    So it stands on its own: there is nothing for a condition to make it depend on, nothing
    to weigh it against, and nothing for the solver to choose. A declaration holding one
    holds nothing else, and every set in it names exactly who and when.
    """
    exclusions = declaration.exclusions
    if len(declaration.lines) > len(exclusions):
        raise _error("EXCLUDE stands on its own line and its own request", exclusions[0].pos)
    if not hard:
        raise _error("EXCLUDE is a fact about the day, so it is MUST_HAPPEN", exclusions[0].pos)
    for line in exclusions:
        _settled(line.who)
        for clause in line.clauses:
            if isinstance(clause, ast.During | ast.On):
                _settled(clause.selector)
            else:
                raise _error(
                    f"EXCLUDE takes DURING and ON, not {CLAUSE_NAMES[type(clause)]}", clause.pos
                )
        _check_clauses(line.clauses, ast.Task(line.label))
    _check_variables(declaration)


def _settled(selector: ast.Selector) -> None:
    """Nothing in an EXCLUDE is the solver's to pick: it is either so or it is not."""
    if selector.quantifier == ast.ANY_OF or ast.picks(selector.expr):
        raise _error("EXCLUDE says who is away, so nothing in it is ANY n", selector.pos)


def _check_line(line: ast.Line) -> None:
    if isinstance(line, ast.Requirement):
        _check_clauses(line.clauses, line.what)
        if line.negated:
            return
        if ast.clause(line.clauses, ast.During) is None:
            raise _error("needs DURING", line.pos)
        _one_at_a_time(line.what)
        role = ast.clause(line.clauses, ast.AsRole)
        _one_at_a_time(role.selector if role else None)
        return
    if isinstance(line, ast.Gap):
        if not line.amount.duration:
            raise _error("GAP needs a duration", line.amount.pos)
        return
    amounts = (
        [p.amount for p in ast.predicates(line.test)]
        if isinstance(line, ast.Condition)
        else [getattr(line, "amount", None)]
    )
    for amount in amounts:
        if amount is not None:
            _check_amount(amount)
    for pattern in ast.patterns(line):
        _check_clauses(pattern.clauses, pattern.what)


def _check_clauses(clauses: tuple[ast.Clause, ...], what: ast.Target) -> None:
    seen: set[type] = set()
    for clause in clauses:
        if type(clause) in seen:
            raise _error(f"{CLAUSE_NAMES[type(clause)]} given twice", clause.pos)
        seen.add(type(clause))
        if isinstance(clause, ast.During) and clause.consecutive:
            selector = clause.selector
            if selector.quantifier == ast.ANY:
                continue  # a count measured in runs, which the parser has seen to
            if selector.quantifier != ast.ANY_OF or selector.n < 2:
                raise _error(
                    "CONSECUTIVE after DURING chooses blocks next to each other, so it needs "
                    "ANY n with n of 2 or more",
                    clause.pos,
                )
        if isinstance(clause, ast.AsRole) and not isinstance(what, ast.Selector):
            raise _error("AS_ROLE needs an activity", clause.pos)
        if isinstance(clause, ast.For) and not isinstance(what, ast.Task):
            raise _error("FOR needs a quoted task", clause.pos)
        if isinstance(clause, ast.With | ast.Without):
            if what is None:
                raise _error("FREE has no instance", clause.pos)
            if clause.selector.quantifier in (ast.EACH, ast.ANY):
                name, q = CLAUSE_NAMES[type(clause)], clause.selector.quantifier
                raise _error(
                    f"{name} counts who is alongside, so it takes ALL or ANY n, not {q}",
                    clause.selector.pos,
                )


def _one_at_a_time(selector: ast.Selector | ast.Task | None) -> None:
    """The activity and role of a requirement take an item, ANY 1 or EACH, and no group."""
    if not isinstance(selector, ast.Selector):
        return
    several = selector.quantifier == ast.ALL or (
        selector.quantifier == ast.ANY_OF and selector.n > 1
    )
    if several or any(ast.groups_in(selector.expr)):
        raise _error("one activity at a time", selector.pos)


def _check_amount(amount: ast.Amount) -> None:
    if amount.value >= 1:
        return
    if amount.bound == ast.AT_LEAST:
        raise _error("amount must be at least 1", amount.pos)
    raise _error("write NOT DO", amount.pos)


def _check_labels(declaration: ast.Declaration) -> None:
    labels: set[str] = set()
    for statement in declaration.statements:
        label = getattr(statement, "label", None)
        if label is None:
            continue
        positive = isinstance(statement, ast.Requirement) and not statement.negated
        if not positive or statement.what is None:
            raise _error("only REQUEST … DO can be labeled", statement.pos)
        if label in labels:
            raise _error(f"label '{label}' defined twice", statement.pos)
        labels.add(label)
    for gap in declaration.gaps:
        for name in (gap.first, gap.second):
            if name not in labels:
                raise _error(f"undefined label '{name}'", gap.pos)


def _check_variables(declaration: ast.Declaration) -> None:
    """A binding line is visible everywhere; an inline `EACH x IN s` in its statement."""
    shared: dict[str, ast.Pos] = {}
    for binding in declaration.bindings:
        _bind(shared, binding.selector)
    for line in declaration.lines:
        if isinstance(line, ast.Binding | ast.Gap):
            continue
        local = dict(shared)
        for _, selector in ast.selectors(line):
            if selector.var is not None:
                _bind(local, selector)
        for expr in ast.set_exprs(line):
            for var in ast.vars_in(expr):
                if var.name not in local:
                    raise _error(f"unknown variable '{var.name}'", var.pos)


def _bind(bound: dict[str, ast.Pos], selector: ast.Selector) -> None:
    if selector.var in bound:
        raise _error(f"variable bound twice: '{selector.var}'", selector.pos)
    bound[selector.var] = selector.pos


def _error(message: str, pos: ast.Pos) -> ast.SkedgeError:
    return ast.SkedgeError(message, pos.line, pos.column)
