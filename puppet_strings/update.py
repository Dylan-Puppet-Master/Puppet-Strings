"""Looking for a newer Puppet Strings, and putting it in place.

The Puppet Master runs a single downloaded file, so an update is one file replacing
another. The running program renames itself out of the way and moves the download in,
which Windows allows for a file that is open and which the other two allow outright.
"""

import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from puppet_strings import __version__

TIMEOUT = 20
# What the platform's own file is called: the spec names each build for its platform.
ASSET_HINTS = {"win32": ".exe", "darwin": "macos", "linux": "linux"}


@dataclass(frozen=True)
class Release:
    """A published version and the file to download for this platform."""

    version: str
    url: str
    notes: str


class UpdateError(Exception):
    """The update could not be fetched or put in place."""


def latest_release(releases_url: str) -> Release | None:
    """Ask GitHub what the newest release is, or None if there is nothing newer."""
    try:
        response = requests.get(releases_url, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as e:  # noqa: BLE001 - never stop the app because a check failed
        raise UpdateError(f"Could not check for updates: {e}") from e
    version = str(data.get("tag_name", "")).lstrip("v")
    asset = _asset(data.get("assets", []))
    if not version or asset is None or not is_newer(version, __version__):
        return None
    return Release(version, asset, str(data.get("body", "")).strip())


def is_newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a later version than `current`."""
    return _parts(candidate) > _parts(current)


def download(release: Release) -> Path:
    """Fetch the release into a temporary file and return where it landed."""
    try:
        response = requests.get(release.url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()
        handle, name = tempfile.mkstemp(prefix="puppet-strings-", suffix=Path(release.url).suffix)
        with os.fdopen(handle, "wb") as out:
            for chunk in response.iter_content(chunk_size=1 << 16):
                out.write(chunk)
    except Exception as e:  # noqa: BLE001 - reported, never swallowed
        raise UpdateError(f"Could not download the update: {e}") from e
    return Path(name)


def install(downloaded: Path) -> Path:
    """Put the download where the running program is. Returns the path to restart."""
    if not getattr(sys, "frozen", False):
        raise UpdateError(
            "This copy of Puppet Strings runs from source, so update it with git instead."
        )
    target = Path(sys.executable)
    previous = target.with_name(target.name + ".old")
    try:
        previous.unlink(missing_ok=True)
        target.rename(previous)
        shutil.move(str(downloaded), str(target))
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as e:
        raise UpdateError(f"Could not replace {target}: {e}") from e
    return target


def _asset(assets) -> str | None:
    hint = ASSET_HINTS.get(sys.platform, sys.platform)
    for asset in assets:
        if hint in asset.get("name", "").lower():
            return asset.get("browser_download_url")
    return None


def _parts(version: str) -> tuple[int, ...]:
    numbers = []
    for piece in version.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers)
