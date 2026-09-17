"""Every Skedge example in the docs must validate and solve against the fixture dataset."""

import re
from dataclasses import replace

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Priority, Request
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import solve
from tests.examples import EXAMPLES


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_doc_example_validates(dataset, name):
    assert validate_request(Request("doc", "", EXAMPLES[name], Priority.HIGH), dataset) is not None


def test_docs_have_every_example():
    assert len(EXAMPLES) == 33


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
    offerings = tuple(r for r in dataset.requests if "generated" in r.tags)
    example = Request("doc", "", skedge, Priority.HIGH)
    single = replace(dataset, requests=offerings + _prerequisites(dataset, skedge) + (example,))
    result = solve(single, Config(time_limit_seconds=10, workers=4))
    assert result.feasible
    assert result.assignments
