"""Attach clauses to verbs.

A clause on a verb's line applies to that verb. A clause on a line with no verb applies
to every verb. A verb may not get the same clause from both places.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from puppet_strings.skedge import ast

SHAREABLE = (ast.On, ast.During, ast.Across, ast.Role, ast.For, ast.MetricClause, ast.Per)


@dataclass(frozen=True)
class ScopedVerb:
    """A verb with every clause that applies to it, keyed by clause type."""

    verb: ast.Verb
    clauses: Mapping[type[ast.Clause], ast.Clause]

    def get(self, kind: type) -> ast.Clause | None:
        """The clause of this type, if the verb has one."""
        return self.clauses.get(kind)


@dataclass(frozen=True)
class ScopedDeclaration:
    """Every verb in a declaration with its clauses, plus the declaration's GAP clauses."""

    verbs: tuple[ScopedVerb, ...]
    gaps: tuple[ast.Gap, ...]


def scope(declaration: ast.Declaration) -> ScopedDeclaration:
    """Resolve clause scoping for a parsed declaration."""
    shared: dict[type[ast.Clause], ast.Clause] = {}
    gaps: list[ast.Gap] = []
    verb_lines: list[tuple[ast.Verb, dict[type[ast.Clause], ast.Clause]]] = []
    for line in declaration.lines:
        verbs = [c for c in line.clauses if isinstance(c, ast.Verb)]
        if len(verbs) > 1:
            raise ast.SkedgeError("one verb per line", verbs[1].pos.line, verbs[1].pos.column)
        own: dict[type[ast.Clause], ast.Clause] = {}
        for clause in line.clauses:
            if isinstance(clause, ast.Verb):
                continue
            if isinstance(clause, ast.Gap):
                gaps.append(clause)
                continue
            target = own if verbs else shared
            if isinstance(clause, ast.Label) and not verbs:
                raise ast.SkedgeError("AS belongs on a verb's line", *_at(clause))
            if type(clause) in target:
                raise ast.SkedgeError(f"{_name(clause)} given twice", *_at(clause))
            target[type(clause)] = clause
        if verbs:
            verb_lines.append((verbs[0], own))
    if not verb_lines:
        raise ast.SkedgeError("a declaration needs at least one verb", 1, 1)
    scoped = []
    for verb, own in verb_lines:
        for kind, clause in own.items():
            if kind in shared:
                raise ast.SkedgeError(
                    f"{_name(clause)} is given here and on a shared line", *_at(clause)
                )
        scoped.append(ScopedVerb(verb, {**shared, **own}))
    return ScopedDeclaration(tuple(scoped), tuple(gaps))


def _name(clause: ast.Clause) -> str:
    return {
        ast.On: "ON",
        ast.During: "DURING",
        ast.Across: "ACROSS",
        ast.Role: "ROLE",
        ast.For: "FOR",
        ast.Label: "AS",
        ast.MetricClause: "~",
        ast.Per: "PER",
    }[type(clause)]


def _at(clause: ast.Clause) -> tuple[int, int]:
    return clause.pos.line, clause.pos.column
