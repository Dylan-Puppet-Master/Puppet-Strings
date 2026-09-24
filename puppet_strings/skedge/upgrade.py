"""Requests written before a change to Skedge, rewritten the way it is written now.

A saved request is the Puppet Master's own work, so a change to the language rewrites it
rather than leaving it to fail validation the day the app is updated. Requests saved
before syntax version 5 are read with the grammar they were written in,
`grammar_v4.lark`, which still parses the spellings it had stopped accepting; the tree
has everything where it was written, so each rewrite is a list of edits to the text.

Each rewrite only ever changes a spelling the language no longer accepts, so running it on
a request that is already up to date changes nothing: text the old grammar cannot read is
left as it is.

Up to version 4:

- A set that is matched rather than chosen — right of NOT, and in a pattern — takes ANY:
  `NOT DO activities.clinics.all` is `NOT DO ANY activities.clinics.all`. Whether a name
  is one thing or a set is a question for the dataset, so a rewrite is given one.
- CONSECUTIVE is on the blocks. `DURING ANY 2 blocks.all CONSECUTIVE` is
  `DURING ANY 2 CONSECUTIVE blocks.all`, and a count measured in runs,
  `AT_MOST 3 CONSECUTIVE <pattern>`, says so in its DURING, `DURING ANY CONSECUTIVE …`, or
  gains one over the whole day, which is what it measured before.
- ALL_OF is ALL and EACH_OF is EACH, as ANY n dropped its `_OF` before them.

Version 5, where a count goes on the set it counts:

- AS_ROLE, FOR, WITH and WITHOUT written before the verb move to the end of the statement.
- `ANY n` is `AT_LEAST n`, and in a binding line `EXACTLY n`. A statement that chose from
  two sets at once, `ANY 2 staff.x DO … DURING ANY 1 blocks.all`, shared the second choice
  between everyone the first chose; that one becomes a binding line, since a count of the
  blocks would now be each person's own.
- A count in front of a pattern moves onto the one set it pooled, in place of its ANY, or
  onto the blocks when it was measured in runs or named none; a length moves onto FOR. A
  count over two pools has no spelling now, and is left for somebody to rewrite.
- `NOT FREE` is `BUSY`. Right of NOT a pool was every one of its items, so it becomes ALL,
  and ALL was all of them together, which is at least one: `AT_LEAST 1`.
"""

import re
from functools import cache
from pathlib import Path

from lark import Lark, Token, Tree, UnexpectedInput

from puppet_strings.model import Dataset
from puppet_strings.skedge.resolve import name_spaces

CLAUSES = ("during", "on", "as_role")  # the clauses whose sets are matched; WITH counts
NEGATED = ("request_not_do", "request_not_free")
PATTERNS = ("pattern_doing", "pattern_free", "pattern_busy", "counted")
AROUND_A_PATTERN = ("request_count", "prefer_count", "prefer_score")  # clauses written outside it
POSITIVE = ("request_do", "request_activity", "request_free")
STATEMENTS = (*POSITIVE, "request_not_do", "request_not_free")
AFTER_THE_VERB = ("as_role", "for_", "with_", "without")


@cache
def _old_parser() -> Lark:
    grammar = (Path(__file__).parent / "grammar_v4.lark").read_text()
    return Lark(grammar, parser="lalr", propagate_positions=True, start="start")


def _tree(text: str) -> Tree | None:
    """The request as the old grammar reads it, or None if it cannot."""
    try:
        return _old_parser().parse(text)
    except UnexpectedInput:
        return None


def upgrade(text: str, dataset: Dataset) -> str:
    """The request as it is written now. Text the old grammar does not parse is left as it is."""
    for rewrite in (_to_four, _clauses_after_the_verb, _counts_on_their_sets):
        tree = _tree(text)
        if tree is None:
            return text
        text = rewrite(text, tree, dataset)
    return text


def _to_four(text: str, tree: Tree, dataset: Dataset) -> str:
    """The rewrites up to syntax version 4."""
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
    return _edited(text, edits)


def _edited(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, words in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
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


# -- version 5 ------------------------------------------------------------------------------


def _clauses_after_the_verb(text: str, tree: Tree, dataset: Dataset) -> str:
    """AS_ROLE, FOR, WITH and WITHOUT describe the activity, so they go after the verb."""
    edits = []
    for node in tree.iter_subtrees():
        if node.data not in (*STATEMENTS, *PATTERNS, "exclude"):
            continue
        verb = _verb_at(node, text)
        if verb is None:
            continue
        moved = []
        for clause in node.children:
            if not (isinstance(clause, Tree) and clause.data in AFTER_THE_VERB):
                continue
            if clause.meta.end_pos > verb:
                continue
            start, stop = clause.meta.start_pos, clause.meta.end_pos
            while stop < len(text) and text[stop] in " \t":
                stop += 1
            edits.append((start, stop, ""))
            moved.append(text[clause.meta.start_pos : clause.meta.end_pos])
        if moved:
            end = node.meta.end_pos
            edits.append((end, end, "".join(f" {clause}" for clause in moved)))
    return _edited(text, edits)


def _verb_at(node: Tree, text: str) -> int | None:
    """Where a statement's DO or FREE starts: after its subject, which is its first set."""
    subject = next((c for c in node.children if isinstance(c, Tree) and c.data == "chooser"), None)
    if subject is None:
        return None
    found = re.compile(r"\b(DO|FREE)\b", re.IGNORECASE).search(
        text, subject.meta.end_pos, node.meta.end_pos
    )
    return found.start() if found else None


def _counts_on_their_sets(text: str, tree: Tree, dataset: Dataset) -> str:
    """ANY n to a count, a count in front of a pattern onto its set, NOT FREE to BUSY."""
    edits: list[tuple[int, int, str]] = []
    bindings: list[str] = []
    taken = set(re.findall(r"[a-z_][a-z0-9_]*", text))
    for node in tree.iter_subtrees_topdown():
        if node.data in ("binding", "define"):
            for any_n in _direct(node, "any_n"):
                edits.append(_counted(any_n, "EXACTLY"))
        elif node.data == "group":
            for any_n in _direct(node, "any_n"):
                edits.append(_counted(any_n, "AT_LEAST"))
        elif node.data in POSITIVE:
            _shared_choices(node, text, edits, bindings, taken)
        elif node.data in NEGATED:
            subject = _direct(node, "chooser")[0]  # left of NOT, the subject is counted
            for any_n in _direct(subject, "any_n"):
                edits.append(_counted(any_n, "AT_LEAST"))
        elif node.data in ("request_count", "prefer_count", "test"):
            amount = next(iter(_direct(node, "amount")), None)
            pattern = next(c for c in node.children if isinstance(c, Tree) and c.data in PATTERNS)
            if amount is not None:
                _move_amount(amount, pattern, text, edits)
        elif node.data == "counted":
            amount = next(iter(_direct(node, "amount")))
            _move_amount(amount, node, text, edits)
        if node.data in ("request_not_free", "pattern_busy"):
            _busy(node, text, edits)
        if node.data in ("with_", "without", "as_role"):
            for chooser in _direct(node, "chooser"):
                for any_n in _direct(chooser, "any_n"):
                    word = "ANY" if node.data == "as_role" else "AT_LEAST"
                    edits.append(_counted(any_n, word))
    if bindings:
        edits.append((0, 0, "".join(f"{line}\n" for line in bindings)))
    return _edited(text, edits)


def _direct(node: Tree, data: str) -> list[Tree]:
    return [c for c in node.children if isinstance(c, Tree) and c.data == data]


def _counted(any_n: Tree, word: str) -> tuple[int, int, str]:
    """`ANY n` as `<word> n`, or as a pool when the word is ANY."""
    n = str(any_n.children[-1])
    written = "ANY" if word == "ANY" else f"{word} {n}"
    return any_n.meta.start_pos, any_n.meta.end_pos, written


def _choosers(node: Tree) -> list[tuple[str, Tree]]:
    """A statement's sets by what they are, subject first, then object, dates and blocks."""
    found = []
    choosers = _direct(node, "chooser")
    if node.data == "request_activity":
        found.append(("what", choosers[0]))
    elif choosers:
        found.append(("who", choosers[0]))
        if len(choosers) > 1:
            found.append(("what", choosers[1]))
    for clause in node.children:
        if isinstance(clause, Tree) and clause.data in ("on", "during"):
            found.append((clause.data, clause.children[0]))
    order = {"who": 0, "what": 1, "on": 2, "during": 3}
    return sorted(found, key=lambda f: order[f[0]])


def _shared_choices(node: Tree, text: str, edits: list, bindings: list, taken: set) -> None:
    """ANY n in a requirement as a count, but after a count of several as a binding.

    Everyone the old ANY 2 chose shared the ANY 1 after it; a count of the blocks after a
    count of two people would be each one's own, so the shared choice is named instead.
    """
    several = False  # whether a count before this one takes more than one item
    for _, chooser in _choosers(node):
        any_n = next(iter(_direct(chooser, "any_n")), None)
        if any_n is None:
            continue
        if not several:
            edits.append(_counted(any_n, "AT_LEAST"))
            several = int(str(any_n.children[-1])) > 1
            continue
        n = str(any_n.children[-1])
        name = _fresh("chosen", taken)
        written = text[any_n.meta.end_pos : chooser.meta.end_pos].strip()
        consecutive = written.upper().startswith("CONSECUTIVE")
        if consecutive:
            return  # a run chosen once has no binding; left for somebody to rewrite
        bindings.append(f"EXACTLY {n} {name} IN {written}")
        edits.append((chooser.meta.start_pos, chooser.meta.end_pos, _bound(name, n)))


def _bound(name: str, n: str) -> str:
    return name if n == "1" else f"ALL {name}"


def _fresh(stem: str, taken: set) -> str:
    i = 1
    while f"{stem}_{i}" in taken:
        i += 1
    taken.add(f"{stem}_{i}")
    return f"{stem}_{i}"


def _move_amount(amount: Tree, pattern: Tree, text: str, edits: list) -> None:
    """A count in front of a pattern onto the set it pooled; a length onto FOR."""
    bound, value = (str(c) for c in amount.children)
    written = f"{bound.upper()} {value}"
    end = pattern.meta.end_pos
    if value[-1] in "mhd":
        if any(isinstance(c, Tree) and c.data == "for_" for c in pattern.children):
            return  # a FOR already: left for somebody to rewrite
        edits.append(_take_out(amount, pattern, text))
        edits.append((end, end, f" FOR {written}"))
        return
    target = _counted_set(pattern)
    if target is None:
        return  # nothing pooled, or two pools: no spelling now
    edits.append(_take_out(amount, pattern, text))
    if target == "day":
        edits.append((end, end, f" DURING {written} blocks.all"))
        return
    if isinstance(target, tuple):
        start = target[1].meta.start_pos
        edits.append((start, start, f"{written} "))
        return
    token = target.children[0]
    edits.append((token.start_pos, token.end_pos, written))


def _take_out(amount: Tree, pattern: Tree, text: str) -> tuple[int, int, str]:
    """The amount's words, and the space after them."""
    stop = amount.meta.end_pos
    while stop < len(text) and text[stop] in " \t":
        stop += 1
    return amount.meta.start_pos, stop, ""


def _counted_set(pattern: Tree):
    """The chooser a count goes on, or "day" for the blocks of a pattern that named none.

    The old count was of assignments. Runs of blocks are counted on the blocks. Otherwise
    each pooled set of people, dates or blocks, a missing DURING being the whole day, is one
    the assignments spread over, and a count over one of them is a count of its members;
    over two there is no spelling now. A person holds one activity a block, so a pool of
    activities is counted only where nothing else is pooled.
    """
    choosers = _choosers(pattern)
    during = next((c for field, c in choosers if field == "during"), None)
    if during is not None and _is(during.children[0], "ANY") and _consecutive(during):
        return during
    pools = [
        c for field, c in choosers if field != "what" and _is(c.children[0], "ANY") and _pooled(c)
    ]
    if during is None:
        pools.append("day")
    if len(pools) == 1:
        return pools[0]
    if pools:
        return None
    what = next((c for field, c in choosers if field == "what"), None)
    if what is not None and _is(what.children[0], "ANY") and _pooled(what):
        return what
    if len(during.children) == 1:  # one block, counted once: `DURING AT_LEAST 1 blocks.x`
        return ("in front of", during)
    return None


def _pooled(chooser: Tree) -> bool:
    """A bare ANY on a set, rather than ANY n."""
    return len(chooser.children) > 1


def _consecutive(chooser: Tree) -> bool:
    return any(_is(c, "CONSECUTIVE") for c in chooser.children)


def _busy(node: Tree, text: str, edits: list) -> None:
    """`NOT FREE` is `BUSY`; right of NOT, a pool was every item and ALL was at least one."""
    found = re.compile(r"\bNOT\s+FREE\b", re.IGNORECASE).search(
        text, node.meta.start_pos, node.meta.end_pos
    )
    if found is None:
        return
    edits.append((found.start(), found.end(), "BUSY"))
    if node.data != "request_not_free":
        return
    during = False
    for clause in node.children:
        if not (isinstance(clause, Tree) and clause.data in ("during", "on")):
            continue
        during |= clause.data == "during"
        chooser = clause.children[0]
        first = chooser.children[0]
        if _is(first, "ANY"):
            edits.append((first.start_pos, first.end_pos, "ALL"))
        elif _is(first, "ALL"):
            edits.append((first.start_pos, first.end_pos, "AT_LEAST 1"))
    if not during:
        end = node.meta.end_pos
        edits.append((end, end, " DURING ALL blocks.all"))
