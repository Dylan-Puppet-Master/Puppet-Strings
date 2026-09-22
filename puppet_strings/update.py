"""Looking for a newer Puppet Strings, and putting it in place.

The Puppet Master runs a single downloaded file, so an update is one file replacing
another. The running program renames itself out of the way and moves the download in,
which Windows allows for a file that is open and which the other two allow outright.

Linux is released as a tar.gz rather than as the bare executable: the archive carries the
icon and the `install.sh` that writes the desktop entry, which is how the program gets a
launcher and a picture in the menu. An update to such a copy is still one file replacing
another — the executable inside the archive replacing the running one, in the folder it is
already installed in, which is the folder the desktop entry points at. The icon beside it
is refreshed if it is there, and `install.sh` is not run again: the desktop entry it wrote
names the same path and goes on working.
"""

import os
import shutil
import stat
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from puppet_strings import __version__

TIMEOUT = 20
# What the platform's own file is called: the spec names each build for its platform.
ASSET_HINTS = {"win32": ".exe", "darwin": "macos", "linux": "linux"}
ICON = "puppet-strings.png"  # what the Linux package calls the icon the desktop entry uses
EXECUTABLE = "puppet-strings"  # what every build's executable is called, plus its platform


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
    """Put the download where the running program is. Returns the path to restart.

    A download that is an archive is unpacked first and the executable inside it is what
    goes in; anything else it carries that is already installed beside the program — the
    icon — is refreshed at the same time.
    """
    if not getattr(sys, "frozen", False):
        raise UpdateError(
            "This copy of Puppet Strings runs from source, so update it with git instead."
        )
    target = Path(sys.executable)
    unpacked = _unpack(downloaded) if tarfile.is_tarfile(downloaded) else None
    executable = downloaded if unpacked is None else _executable_in(unpacked, target.name)
    previous = target.with_name(target.name + ".old")
    try:
        previous.unlink(missing_ok=True)
        target.rename(previous)
        shutil.move(str(executable), str(target))
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if unpacked is not None:
            _refresh_icon(unpacked, target.parent)
    except OSError as e:
        raise UpdateError(f"Could not replace {target}: {e}") from e
    finally:
        if unpacked is not None:
            shutil.rmtree(unpacked, ignore_errors=True)
    return target


def _unpack(archive: Path) -> Path:
    """Extract an archive into a temporary folder of its own and return it."""
    folder = Path(tempfile.mkdtemp(prefix="puppet-strings-update-"))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="data")  # nothing outside the folder, no links
    except (OSError, tarfile.TarError) as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(f"Could not unpack the update: {e}") from e
    return folder


def _executable_in(folder: Path, name: str) -> Path:
    """The program inside an unpacked archive: the one named as the running one is.

    A release whose executable has been renamed — a platform added, a tag changed — is
    still found by the name every build of it starts with, so one odd release is a name to
    look at rather than an update nobody can take.
    """
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for p in files:
        if p.name == name:
            return p
    for p in files:
        if p.name.startswith(EXECUTABLE) and p.suffix not in (".png", ".sh", ".txt", ".md"):
            return p
    held = ", ".join(p.name for p in files) or "nothing"
    raise UpdateError(f"The update holds no {name}; it holds {held}")


def _refresh_icon(folder: Path, beside: Path) -> None:
    """Replace the icon the desktop entry points at, if this copy was installed with one.

    Only if it is already there: a copy run from a downloads folder has no desktop entry
    and no use for a picture next to it, and an update is no place to start leaving files
    somebody did not ask for.
    """
    new_icon = next((p for p in folder.rglob(ICON)), None)
    if new_icon is not None and (beside / ICON).is_file():
        shutil.copy2(new_icon, beside / ICON)


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
