"""Requests written before a change to Skedge, rewritten the way it is written now.

A saved request is the Puppet Master's own work, so a change to the language rewrites it
rather than leaving it to fail validation the day the app is updated. The old spellings
still parse, which is what lets a rewrite find them: the builder refuses them with a
message saying what to write instead, but the parse tree has them where they were written.

Each rewrite only ever changes a spelling the language no longer accepts, so running it on
a request that is already up to date changes nothing.

- A set that is matched rather than chosen — right of NOT, and in a pattern — takes ANY:
  `NOT DO activities.clinics.all` is `NOT DO ANY activities.clinics.all`. Whether a name
  is one thing or a set is a question for the dataset, so a rewrite is given one.
- CONSECUTIVE is on the blocks. `DURING ANY 2 blocks.all CONSECUTIVE` is
  `DURING ANY 2 CONSECUTIVE blocks.all`, and a count measured in runs,
  `AT_MOST 3 CONSECUTIVE <pattern>`, says so in its DURING, `DURING ANY CONSECUTIVE …`, or
  gains one over the whole day, which is what it measured before.
- ALL_OF is ALL and EACH_OF is EACH, as ANY n dropped its `_OF` before them.
"""

from lark import Token, Tree

from puppet_strings.model import Dataset
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.parser import parse_tree
from puppet_strings.skedge.resolve import name_spaces

CLAUSES = ("during", "on", "as_role")  # the clauses whose sets are matched; WITH counts
NEGATED = ("request_not_do", "request_not_free")
PATTERNS = ("pattern_doing", "pattern_free", "pattern_busy", "counted")
AROUND_A_PATTERN = ("request_count", "prefer_count", "prefer_score")  # clauses written outside it


def upgrade(text: str, dataset: Dataset) -> str:
    """The request as it is written now. Text that does not parse is left as it is."""
    try:
        tree = parse_tree(text)
    except SkedgeError:
        return text
    names = name_spaces(dataset)
    definitions = {
        str(line.children[0]): line.children[1]
        for line in tree.find_data("define")
        if len(line.children) == 2  # with a quantifier it is a binding line
    }
    edits: list[tuple[int, int, str]] = []
    runs: set[int] = set()  # the choosers a moved CONSECUTIVE has already given their ANY
    for token in tree.scan_values(lambda v: _is(v, "ALL") or _is(v, "EACH")):
        if str(token).upper() != token.type:  # ALL_OF or EACH_OF, in whatever case
            edits.append((token.start_pos, token.end_pos, token.type))
    for node in tree.iter_subtrees():
        _move_consecutive(node, edits, runs)
    for node in tree.iter_subtrees():
        for chooser in _matched(node):
            if id(chooser) in runs or len(chooser.children) != 1:
                continue
            if not _one(chooser.children[0], names, definitions):
                edits.append((chooser.meta.start_pos, chooser.meta.start_pos, "ANY "))
    for start, end, words in sorted(edits, reverse=True):
        text = text[:start] + words + text[end:]
    return text


def _move_consecutive(node: Tree, edits: list, runs: set) -> None:
    """CONSECUTIVE from after an amount, or after a DURING's blocks, to before the blocks."""
    token = next((c for c in node.children if _is(c, "CONSECUTIVE")), None)
    if token is None:
        return
    if node.data == "during":
        chooser = node.children[0]
        edits.append((chooser.meta.end_pos, token.end_pos, ""))
        quantifier = chooser.children[0]
        if isinstance(quantifier, Tree) and quantifier.data == "any_n":
            edits.append((quantifier.meta.end_pos, quantifier.meta.end_pos, " CONSECUTIVE"))
        elif isinstance(quantifier, Token) and quantifier.type in ("ANY", "ALL"):
            edits.append((quantifier.end_pos, quantifier.end_pos, " CONSECUTIVE"))
        else:  # moved, not dropped, so a request that was wrong still says so
            edits.append((chooser.meta.start_pos, chooser.meta.start_pos, "CONSECUTIVE "))
        return
    if node.data not in ("request_count", "prefer_count", "test"):
        return
    amount = next(c for c in node.children if isinstance(c, Tree) and c.data == "amount")
    edits.append((amount.meta.end_pos, token.end_pos, ""))
    pattern = next(c for c in node.children if isinstance(c, Tree) and c.data in PATTERNS)
    during = next(
        (
            c
            for c in (*node.children, *pattern.children)
            if isinstance(c, Tree) and c.data == "during"
        ),
        None,
    )
    if during is None:
        end = pattern.meta.end_pos
        edits.append((end, end, " DURING ANY CONSECUTIVE blocks.all"))
        return
    chooser = during.children[0]
    runs.add(id(chooser))
    first = chooser.children[0]
    if _is(first, "ANY"):
        edits.append((first.end_pos, first.end_pos, " CONSECUTIVE"))
    elif len(chooser.children) == 1:
        edits.append((chooser.meta.start_pos, chooser.meta.start_pos, "ANY CONSECUTIVE "))


def _is(item, kind: str) -> bool:
    return isinstance(item, Token) and item.type == kind


def _matched(node: Tree):
    """The choosers under a node whose sets are matched rather than chosen."""
    choosers = [c for c in node.children if isinstance(c, Tree) and c.data == "chooser"]
    if node.data in NEGATED:
        yield from choosers[1:]  # the subject is left of NOT, and chooses
    elif node.data in PATTERNS:
        yield from choosers
    elif node.data not in AROUND_A_PATTERN:
        return
    for clause in node.children:
        if isinstance(clause, Tree) and clause.data in CLAUSES:
            yield clause.children[0]


def _one(node, names, definitions) -> bool:
    """Whether a set as written is one thing. A name the dataset does not know is a set."""
    if isinstance(node, Token):
        if node.type == "REF":
            namespace, name = str(node).split(".", 1)
            named = names.get(namespace, {}).get(name)
            return named is not None and named.single
        if node.type == "NAME" and str(node) in definitions:
            return _one(definitions[str(node)], names, definitions)
        return True  # a date, or a name a binding line gives, which is one thing already
    if node.data == "setop":
        return len(node.children) == 1 and _one(node.children[0], names, definitions)
    return node.data in ("date_offset", "call")  # a call is its row, or its own default
