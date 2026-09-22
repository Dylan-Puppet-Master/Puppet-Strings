"""The specification is checked against the code, so the two cannot drift apart."""

import re
from pathlib import Path

import pytest

from puppet_strings.model import Priority
from puppet_strings.skedge.resolve import name_listing

ROOT = Path(__file__).parent.parent
SPEC = (ROOT / "docs" / "spec.md").read_text()
GRAMMAR = ROOT / "puppet_strings" / "skedge" / "grammar.lark"
SOURCE = "\n".join(p.read_text() for p in (ROOT / "puppet_strings").rglob("*.py"))
PLACEHOLDER = "…"


def section(title):
    """The text of one numbered section."""
    body = re.search(rf"^## \d+\. {title}\n(.*?)(?=^## |\Z)", SPEC, re.S | re.M)
    assert body, f"the spec has no section called {title}"
    return body.group(1)


def first_column(text):
    """Every backticked name in the first cell of the first table in some text."""
    table = []
    for line in text.splitlines():
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    assert len(table) > 2, "expected a table with a backticked first column"
    names = []
    for row in table[2:]:  # past the header and its underline
        names += re.findall(r"`([^`]+)`", row.split("|")[1])
    assert names, "expected backticked names in the first column"
    return names


def test_the_spec_carries_the_grammar_the_parser_uses():
    block = re.search(r"```lark\n(.*?)```", SPEC, re.S).group(1)
    assert block.rstrip("\n") == GRAMMAR.read_text().rstrip("\n")


def test_every_keyword_the_spec_lists_is_in_the_grammar():
    keywords = re.search(r"\| Keyword \| Either case, upper by convention: (.*?) \|", SPEC)
    listed = re.findall(r"`([A-Za-z_]+)`", keywords.group(1))
    assert len(listed) > 20
    grammar = GRAMMAR.read_text()
    for keyword in listed:
        word = "ANY_[1-9][0-9]*_OF" if keyword == "ANY_n_OF" else keyword
        assert f"/{word}\\b/i" in grammar, f"{keyword} is not a keyword of the grammar"


def test_every_namespace_the_spec_lists_exists(dataset):
    assert first_column(section("Names")) == list(name_listing(dataset))


def test_every_priority_the_spec_lists_exists():
    assert first_column(section("Priorities and scoring")) == [p.value for p in Priority]


def messages():
    return first_column(section("Errors"))


@pytest.mark.parametrize("message", messages())
def test_every_error_the_spec_quotes_exists_in_the_code(message):
    if message in SOURCE:
        return
    assert PLACEHOLDER in message, f"the spec quotes an error the code does not raise: {message}"


def test_almost_every_error_is_quoted_exactly():
    """A row may use … where the message interpolates, but only where it has to."""
    rows = messages()
    assert len([m for m in rows if m not in SOURCE]) <= 2
    assert len(rows) > 30
