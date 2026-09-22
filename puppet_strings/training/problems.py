"""The practice problems: plain-English requests, and the Skedge each one comes to.

They live in `problems/*.toml`, one file per level in the order they are taken, so adding a
problem is adding a few lines of text. A problem says what is asked, at what priority, on
which day of the session, and gives one answer that does it; `alternatives` are other
answers that do exactly the same, shown once it is solved, and `wrong` are near misses the
checker must tell apart from it. The test suite holds every problem to all three.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from puppet_strings.model import Priority

FOLDER = Path(__file__).parent / "problems"


@dataclass(frozen=True)
class Problem:
    """One thing to write in Skedge."""

    id: str
    title: str
    prompt: str
    answer: str
    priority: Priority
    day: date
    hints: tuple[str, ...] = ()
    explain: str = ""
    alternatives: tuple[str, ...] = ()
    wrong: tuple[str, ...] = ()


@dataclass(frozen=True)
class Level:
    """A run of problems about one idea, taken in order."""

    id: str
    name: str
    blurb: str
    teaches: str  # a short reference card: what the level introduces, in Skedge
    problems: tuple[Problem, ...]


def load_levels(folder: Path = FOLDER) -> tuple[Level, ...]:
    """Every level, in file-name order."""
    return tuple(_level(path) for path in sorted(folder.glob("*.toml")))


def _level(path: Path) -> Level:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    head = data["level"]
    day = date.fromisoformat(head.get("day", "2026-08-04"))
    problems = tuple(_problem(p, day) for p in data.get("problem", []))
    return Level(path.stem, head["name"], head["blurb"], head.get("teaches", ""), problems)


def _problem(data: dict, day: date) -> Problem:
    return Problem(
        id=data["id"],
        title=data["title"],
        prompt=data["prompt"].strip(),
        answer=data["answer"].strip(),
        priority=Priority(data.get("priority", "HIGH")),
        day=date.fromisoformat(data["day"]) if "day" in data else day,
        hints=tuple(data.get("hints", ())),
        explain=data.get("explain", "").strip(),
        alternatives=tuple(a.strip() for a in data.get("alternatives", ())),
        wrong=tuple(w.strip() for w in data.get("wrong", ())),
    )
