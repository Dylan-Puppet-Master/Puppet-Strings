"""Configuration file: spreadsheet ids, tab names, credentials, solver settings."""

import os
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from puppet_strings.settings import load_settings
from puppet_strings.sheets.source import DATE_ORDERS, MONTH_FIRST, parse_time

DEFAULT_PATH = Path("~/.config/puppet_strings/config.toml")
DEFAULT_TOKEN = Path("~/.config/puppet_strings/token.json")
DEFAULT_CLIENT = Path("~/.config/puppet_strings/oauth_client.json")

DEFAULT_REMAINDER = "DYOW/WPs"  # label for the unassigned part of a partly used block
DEFAULT_RELEASES = "https://api.github.com/repos/Dylan-Puppet-Master/Puppet-Strings/releases/latest"

DEFAULT_TABS = {
    "clinics": "Clinics",
    "offerings": "Offerings",
    "skills": "Skills",
    "position_skills": "Positions",
    "blocks": "Blocks",
    "calendar": "Calendar",
    "cabin_act_board": "Board",  # of a cabin act sheet; its Support Requests tab is not read
    "requests": "Requests",  # the old one-tab Requests, read only by split-requests
    "mappings": "Mappings",
    "adjustments": "Adjustments",
    "assignments": "Assignments",  # the rows a solve is read back from
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
    # The OAuth client. A release has camp's built in, so a downloaded copy signs in with
    # nothing to set up; a source checkout falls back to the JSON file named here.
    client_id: str = ""
    client_secret: str = ""
    client_secrets: Path = DEFAULT_CLIENT
    token: Path = DEFAULT_TOKEN  # where the signed-in account is remembered
    releases_url: str = DEFAULT_RELEASES
    midday: time = time(12, 0)
    date_order: str = MONTH_FIRST  # how to read 6/7/2026 on a sheet that writes dates so
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
    built_in = _built_in()
    if not path.exists():
        return Config(sheets=chosen.ids("sheets"), folders=chosen.ids("folders"), **built_in)
    data = tomllib.loads(path.read_text())
    solver = data.get("solver", {})
    auth = data.get("auth", {})
    day = data.get("day", {})
    return Config(
        sheets={**data.get("sheets", {}), **chosen.ids("sheets")},
        folders={**data.get("folders", {}), **chosen.ids("folders")},
        tabs={**DEFAULT_TABS, **data.get("tabs", {})},
        credentials=Path(auth.get("credentials", Config.credentials)).expanduser(),
        client_id=auth.get("client_id", built_in["client_id"]),
        client_secret=auth.get("client_secret", built_in["client_secret"]),
        client_secrets=Path(auth.get("client_secrets", Config.client_secrets)).expanduser(),
        token=Path(auth.get("token", Config.token)).expanduser(),
        releases_url=data.get("updates", {}).get("releases_url", built_in["releases_url"]),
        midday=parse_time(day.get("midday", "12:00"), str(path)),
        date_order=_date_order(day.get("date_order", MONTH_FIRST), str(path)),
        remainder=data.get("views", {}).get("remainder", DEFAULT_REMAINDER),
        time_limit_seconds=solver.get("time_limit_seconds", Config.time_limit_seconds),
        tidy_seconds=solver.get("tidy_seconds", Config.tidy_seconds),
        workers=solver.get("workers", Config.workers),
        random_seed=solver.get("random_seed", Config.random_seed),
    )


def _built_in() -> dict[str, str]:
    """What the release build put in: the OAuth client and where to look for updates.

    Blank in the repository, so a source checkout behaves exactly as it did — the client
    comes from the JSON file and updates from the default feed. A config file still
    overrides either, which is how a build can be pointed somewhere else without rebuilding.
    """
    from puppet_strings.built_in import SETTINGS

    return {
        "client_id": SETTINGS.get("client_id", ""),
        "client_secret": SETTINGS.get("client_secret", ""),
        "releases_url": SETTINGS.get("releases_url", DEFAULT_RELEASES),
    }


def _date_order(value: str, where: str) -> str:
    """Which way round a numeric date is written, checked so a typo is not a silent month."""
    if value not in DATE_ORDERS:
        raise ValueError(f"{where}: date_order must be one of {', '.join(DATE_ORDERS)}")
    return value
