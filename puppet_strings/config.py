"""Configuration file: spreadsheet ids, tab names, credentials, solver settings."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/puppet_strings/config.toml")

DEFAULT_REMAINDER = "DYOW/WPs"  # label for the unassigned part of a partly used block

DEFAULT_TABS = {
    "clinics": "Clinics",
    "offerings": "Offerings",
    "skills": "Skills",
    "position_skills": "Positions",
    "staff_categories": "Categories",
    "blocks": "Blocks",
    "calendar": "Calendar",
    "requests": "Requests",
    "metrics": "Metrics",
    "adjustments": "Adjustments",
    "staff_view": "Staff View",
    "clinic_view": "Clinic View",
    "report": "Report",
    "changes": "Changes",
}


@dataclass(frozen=True)
class Config:
    """Settings read from config.toml."""

    sheets: dict[str, str] = field(default_factory=dict)
    tabs: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TABS))
    credentials: Path = Path("~/.config/puppet_strings/service_account.json")
    remainder: str = DEFAULT_REMAINDER
    time_limit_seconds: float = 30.0
    tidy_seconds: float = 2.0
    workers: int = 8
    random_seed: int = 0


def load_config(path: Path | None = None) -> Config:
    """Read the config file; a missing file yields defaults."""
    path = path or Path(os.environ.get("PUPPET_STRINGS_CONFIG", DEFAULT_PATH))
    path = path.expanduser()
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    solver = data.get("solver", {})
    return Config(
        sheets=data.get("sheets", {}),
        tabs={**DEFAULT_TABS, **data.get("tabs", {})},
        credentials=Path(data.get("auth", {}).get("credentials", Config.credentials)).expanduser(),
        remainder=data.get("views", {}).get("remainder", DEFAULT_REMAINDER),
        time_limit_seconds=solver.get("time_limit_seconds", Config.time_limit_seconds),
        tidy_seconds=solver.get("tidy_seconds", Config.tidy_seconds),
        workers=solver.get("workers", Config.workers),
        random_seed=solver.get("random_seed", Config.random_seed),
    )
