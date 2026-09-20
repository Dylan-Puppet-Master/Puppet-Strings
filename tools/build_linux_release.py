"""Package the Linux executable with a desktop launcher and icon."""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

SOURCE = DIST / "puppet-strings-linux"
ICON = ROOT / "build" / "icon.png"

PACKAGE_DIR = DIST / "puppet-strings-linux-package"
ARCHIVE = DIST / "puppet-strings-linux.tar.gz"


def main() -> None:
    """Package the Linux executable, icon, and desktop launcher as a tar.gz."""
    if not SOURCE.is_file():
        raise SystemExit(f"Missing executable: {SOURCE}")

    if not ICON.is_file():
        raise SystemExit(f"Missing icon: {ICON}")

    if PACKAGE_DIR.exists():
        if PACKAGE_DIR.is_dir():
            shutil.rmtree(PACKAGE_DIR)
        else:
            PACKAGE_DIR.unlink()

    if ARCHIVE.exists():
        ARCHIVE.unlink()

    PACKAGE_DIR.mkdir(parents=True)

    executable = PACKAGE_DIR / "puppet-strings-linux"
    shutil.copy2(SOURCE, executable)
    executable.chmod(executable.stat().st_mode | 0o111)

    shutil.copy2(ICON, PACKAGE_DIR / "puppet-strings.png")

    desktop = PACKAGE_DIR / "puppet-strings.desktop"
    desktop.write_text(
        """\
[Desktop Entry]
Name=Puppet Strings
Comment=Puppet Strings
Exec=./puppet-strings-linux
Icon=./puppet-strings.png
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=true
""",
        encoding="utf-8",
    )

    with tarfile.open(ARCHIVE, "w:gz") as tar:
        tar.add(
            PACKAGE_DIR,
            arcname="puppet-strings-linux",
        )

    shutil.rmtree(PACKAGE_DIR)

    print(f"Created {ARCHIVE}")


if __name__ == "__main__":
    main()
