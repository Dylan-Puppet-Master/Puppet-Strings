"""Every Skedge example in the docs must validate and solve against the fixture dataset."""

import re
from dataclasses import replace

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Priority, Request
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import solve
from tests.examples import EXAMPLES


def as_written(skedge: str) -> Request:
    """One example as a request. An EXCLUDE is a fact about the day, so it is MUST_HAPPEN."""
    hard = "EXCLUDE" in skedge.upper()
    return Request("doc", "", skedge, Priority.MUST_HAPPEN if hard else Priority.HIGH)


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_doc_example_validates(dataset, name):
    assert validate_request(as_written(EXAMPLES[name]), dataset) is not None


def test_docs_have_every_example():
    assert len(EXAMPLES) == 63


def _prerequisites(dataset, skedge):
    """Sample requests that ask for a quoted task the example only steers.

    An example such as `NOT DO 'break'` says where breaks go, not that they happen, so it
    needs whatever asks for them before it means anything.
    """
    quoted = set(re.findall(r"'([^']*)'", skedge))
    return tuple(
        request
        for request in dataset.requests
        if any(f"DO '{text}'" in request.skedge for text in quoted)
    )


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_doc_example_solves(dataset, name):
    skedge = EXAMPLES[name]
    offerings = tuple(r for r in dataset.requests if "clinic_import" in r.tags)
    example = as_written(skedge)
    single = replace(dataset, requests=offerings + _prerequisites(dataset, skedge) + (example,))
    result = solve(single, Config(tier_seconds_limit=10, tidy_seconds=1, workers=4))
    assert result.feasible
    assert result.assignments
