"""Configuration file: spreadsheet ids, tab names, credentials, solver settings."""

import os
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from puppet_strings.settings import load_settings
from puppet_strings.sheets.source import parse_time

DEFAULT_PATH = Path("~/.config/puppet_strings/config.toml")
DEFAULT_TOKEN = Path("~/.config/puppet_strings/token.json")
DEFAULT_CLIENT = Path("~/.config/puppet_strings/oauth_client.json")

DEFAULT_REMAINDER = "DYOW/WPs"  # label for the unassigned part of a partly used block

DEFAULT_TABS = {
    "clinics": "Clinics",
    "offerings": "Offerings",
    "skills": "Skills",
    "position_skills": "Positions",
    "staff_categories": "Categories",
    "blocks": "Blocks",
    "calendar": "Calendar",
    "cabin_act_board": "Board",  # of a cabin act sheet; its Support Requests tab is not read
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
    folders: dict[str, str] = field(default_factory=dict)  # a folder of sheets, all read
    tabs: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TABS))
    credentials: Path = Path("~/.config/puppet_strings/service_account.json")
    client_secrets: Path = DEFAULT_CLIENT  # the OAuth client to sign in with
    token: Path = DEFAULT_TOKEN  # where the signed-in account is remembered
    midday: time = time(12, 0)
    remainder: str = DEFAULT_REMAINDER
    time_limit_seconds: float = 30.0
    tidy_seconds: float = 2.0
    workers: int = 8
    random_seed: int = 0


def load_config(path: Path | None = None) -> Config:
    """Read the config file and the choices made in the app; a missing file yields defaults.

    Sheets chosen in the Configure pane win over any written into config.toml, so moving a
    sheet over is one click and needs no edit to the file it used to be named in.
    """
    path = path or Path(os.environ.get("PUPPET_STRINGS_CONFIG", DEFAULT_PATH))
    path = path.expanduser()
    chosen = load_settings()
    if not path.exists():
        return Config(sheets=chosen.ids("sheets"), folders=chosen.ids("folders"))
    data = tomllib.loads(path.read_text())
    solver = data.get("solver", {})
    auth = data.get("auth", {})
    return Config(
        sheets={**data.get("sheets", {}), **chosen.ids("sheets")},
        folders={**data.get("folders", {}), **chosen.ids("folders")},
        tabs={**DEFAULT_TABS, **data.get("tabs", {})},
        credentials=Path(auth.get("credentials", Config.credentials)).expanduser(),
        client_secrets=Path(auth.get("client_secrets", Config.client_secrets)).expanduser(),
        token=Path(auth.get("token", Config.token)).expanduser(),
        midday=parse_time(data.get("day", {}).get("midday", "12:00"), str(path)),
        remainder=data.get("views", {}).get("remainder", DEFAULT_REMAINDER),
        time_limit_seconds=solver.get("time_limit_seconds", Config.time_limit_seconds),
        tidy_seconds=solver.get("tidy_seconds", Config.tidy_seconds),
        workers=solver.get("workers", Config.workers),
        random_seed=solver.get("random_seed", Config.random_seed),
    )
