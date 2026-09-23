"""Which spreadsheets and folders Puppet Strings reads, chosen in the app rather than typed.

Spreadsheet ids used to be written into config.toml by hand, which meant knowing what a
Drive id is and where to find one. The directories to look in live here instead, in a file
the Configure pane writes, alongside the name each was chosen under so the pane can show
the folder rather than its id. config.toml is still read first, so an install that names
its spreadsheets there keeps working; `sheets` is kept for exactly that.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/puppet_strings/settings.json")

# Nothing but directories is asked for. What is inside the root is found by name -- a
# spreadsheet called Skills is the Skills sheet, a folder called 2027 is that year -- so
# setting up is choosing where to look, not listing what is there.
FOLDERS = (
    (
        "root",
        "Root",
        "Holds a folder per year, and the reference sheets named Clinic_Data, "
        "Clinic_Schedule, Skills and Config",
    ),
    ("cabin_acts", "Cabin Acts", "One cabin act sheet per session and week"),
)


@dataclass(frozen=True)
class Chosen:
    """A spreadsheet or folder picked in the Drive browser: its id and what it was called."""

    id: str
    name: str = ""


@dataclass(frozen=True)
class Settings:
    """The choices made in the app: the Configure pane's, and each group's own list.

    `group_tabs` is the request list a new request in a group goes in, set by
    right-clicking the group. It lives here because a group is nothing but a label its
    requests carry: there is no row anywhere to hang it on.
    """

    sheets: dict[str, Chosen] = field(default_factory=dict)
    folders: dict[str, Chosen] = field(default_factory=dict)
    group_tabs: dict[str, str] = field(default_factory=dict)

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
    tabs = data.get("group_tabs")
    return Settings(
        sheets=_chosen(data.get("sheets")),
        folders=_chosen(data.get("folders")),
        group_tabs={
            str(group): str(tab)
            for group, tab in (tabs.items() if isinstance(tabs, dict) else ())
            if tab
        },
    )


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
    data["group_tabs"] = dict(settings.group_tabs)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _chosen(data: object) -> dict[str, Chosen]:
    if not isinstance(data, dict):
        return {}
    return {
        name: Chosen(row.get("id", ""), row.get("name", ""))
        for name, row in data.items()
        if isinstance(row, dict) and row.get("id")
    }
