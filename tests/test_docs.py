"""Every Skedge example in the docs must validate against the fixture dataset."""

import re
from pathlib import Path

import pytest

from puppet_strings.model import Priority, Request
from puppet_strings.skedge.validate import validate_request

DOCS = Path(__file__).parent.parent / "docs" / "skedge.md"
EXAMPLES = re.findall(r"```skedge\n(.*?)```", DOCS.read_text(), re.S)


@pytest.mark.parametrize("skedge", EXAMPLES, ids=[e.splitlines()[-1][:30] for e in EXAMPLES])
def test_doc_example_validates(dataset, skedge):
    assert validate_request(Request("doc", "", skedge, Priority.HIGH), dataset)


def test_docs_have_every_proposal_example():
    assert len(EXAMPLES) == 21


def _prerequisites(dataset, skedge):
    """Sample requests that ask for a quoted task the example only scores.

    An example such as `AVOID 'break'` says where breaks go, not that they happen, so it
    needs whatever asks for them before it means anything.
    """
    quoted = set(re.findall(r"'([^']*)'", skedge))
    return tuple(
        request
        for request in dataset.requests
        if any(f"TASK '{text}'" in request.skedge for text in quoted)
    )


@pytest.mark.parametrize("skedge", EXAMPLES, ids=[e.splitlines()[-1][:30] for e in EXAMPLES])
def test_doc_example_solves(dataset, skedge):
    from dataclasses import replace

    from puppet_strings.config import Config
    from puppet_strings.solver.solve import solve

    offerings = tuple(r for r in dataset.requests if "generated" in r.tags)
    example = Request("doc", "", skedge, Priority.HIGH)
    single = replace(dataset, requests=offerings + _prerequisites(dataset, skedge) + (example,))
    result = solve(single, Config(time_limit_seconds=10, workers=4))
    assert result.feasible
    assert result.assignments
