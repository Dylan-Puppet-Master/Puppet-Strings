"""What a trainee has done: which problems are solved, and what they last wrote in each.

Kept beside the app's own settings, in a file of its own, so that clearing it starts the
trainer over without touching anything the request manager reads.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/puppet_strings/training.json")


@dataclass
class Attempt:
    """One problem's record."""

    solved: bool = False
    tries: int = 0
    draft: str = ""


@dataclass
class Progress:
    """Every problem's record, and where the trainee was."""

    problems: dict[str, Attempt] = field(default_factory=dict)
    current: str = ""
    welcomed: bool = False
    path: Path = DEFAULT_PATH

    def of(self, problem_id: str) -> Attempt:
        """The record of a problem, made empty the first time it is asked for."""
        return self.problems.setdefault(problem_id, Attempt())

    def save(self) -> None:
        """Write the file. A trainer that cannot write its progress still trains."""
        path = self.path.expanduser()
        data = {
            "current": self.current,
            "welcomed": self.welcomed,
            "problems": {k: asdict(v) for k, v in self.problems.items()},
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass


def load_progress(path: Path = DEFAULT_PATH) -> Progress:
    """The saved progress, or a fresh start if there is none or it cannot be read."""
    try:
        data = json.loads(path.expanduser().read_text())
        problems = {k: Attempt(**v) for k, v in data.get("problems", {}).items()}
        return Progress(problems, data.get("current", ""), data.get("welcomed", False), path)
    except (OSError, ValueError, TypeError):
        return Progress(path=path)
