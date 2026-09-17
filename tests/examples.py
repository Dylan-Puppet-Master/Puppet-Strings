"""Every Skedge example in the docs, keyed by the heading it sits under."""

import re
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"
PAGES = ("skedge.md", "spec.md", "same-day.md")


def examples() -> dict[str, str]:
    """Each ```skedge block in the docs, in order, keyed by its page, heading and position."""
    found: dict[str, str] = {}
    for page in PAGES:
        heading = ""
        text = (DOCS / page).read_text()
        for line, block in re.findall(r"^(#+ [^\n]*)|```skedge\n(.*?)```", text, re.S | re.M):
            if line:
                heading = line.lstrip("# ").lower()
                continue
            key = f"{page[:-3]}: {heading}"
            n = sum(1 for k in found if k.startswith(key))
            found[f"{key} #{n + 1}" if n else key] = block
    return found


EXAMPLES = examples()
