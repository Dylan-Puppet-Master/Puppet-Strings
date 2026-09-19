"""Which spreadsheets and folders Puppet Strings reads, chosen in the app rather than typed.

Spreadsheet ids used to be written into config.toml by hand, which meant knowing what a
Drive id is and where to find one. They live here instead, in a file the Configure pane
writes, alongside the name each was chosen under so the pane can show the sheet rather
than its id. config.toml is still read first, so an install that predates this keeps
working and can be moved over one sheet at a time.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/puppet_strings/settings.json")

# Every spreadsheet the program reads, with what it is for, in the order the pane lists them.
SHEETS = (
    ("clinic_data", "Clinic Data", "Every clinic, its category and its positions"),
    ("clinic_schedule", "Clinic Schedule", "The Offerings grid of what runs when"),
    ("skills", "Skills", "Who is checked off on what, and each position's skill"),
    ("staff_categories", "Staff Categories", "One column per category of staff"),
    ("config", "Config", "Blocks, Calendar, Requests, Metrics and Adjustments"),
    ("published", "Published Schedules", "One tab per published day"),
)

# Folders of sheets rather than one sheet: every spreadsheet inside is read.
FOLDERS = (("cabin_acts", "Cabin Acts", "One cabin act sheet per session and week"),)


@dataclass(frozen=True)
class Chosen:
    """A spreadsheet or folder picked in the Drive browser: its id and what it was called."""

    id: str
    name: str = ""


@dataclass(frozen=True)
class Settings:
    """The choices made in the Configure pane."""

    sheets: dict[str, Chosen] = field(default_factory=dict)
    folders: dict[str, Chosen] = field(default_factory=dict)

    def ids(self, kind: str) -> dict[str, str]:
        """Just the ids of `sheets` or `folders`, which is what a Source wants."""
        return {name: chosen.id for name, chosen in getattr(self, kind).items() if chosen.id}


def settings_path(path: Path | None = None) -> Path:
    """Where the choices are kept."""
    return (path or Path(os.environ.get("PUPPET_STRINGS_SETTINGS", DEFAULT_PATH))).expanduser()


def load_settings(path: Path | None = None) -> Settings:
    """Read the choices; a missing or unreadable file means nothing has been chosen."""
    path = settings_path(path)
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Settings()
    return Settings(sheets=_chosen(data.get("sheets")), folders=_chosen(data.get("folders")))


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write the choices, making the config folder if this is the first time."""
    path = settings_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        kind: {
            name: {"id": chosen.id, "name": chosen.name}
            for name, chosen in getattr(settings, kind).items()
        }
        for kind in ("sheets", "folders")
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


def _chosen(data: object) -> dict[str, Chosen]:
    if not isinstance(data, dict):
        return {}
    return {
        name: Chosen(row.get("id", ""), row.get("name", ""))
        for name, row in data.items()
        if isinstance(row, dict) and row.get("id")
    }
