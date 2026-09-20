"""Build platform-specific application icons from the top-level icon.png."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "icon.png"
BUILD = ROOT / "build" / "icon"


def require_source() -> None:
    """Validate that the source icon exists and is square."""
    if not SOURCE.exists():
        raise SystemExit(f"Missing icon source: {SOURCE}")

    with Image.open(SOURCE) as image:
        if image.width != image.height:
            raise SystemExit(
                f"icon.png must be square; got {image.width}x{image.height}"
            )


def build_windows() -> Path:
    """Build a Windows ICO file containing multiple icon sizes."""
    output = BUILD.with_suffix(".ico")
    output.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as image:
        image.convert("RGBA").save(
            output,
            format="ICO",
            sizes=[
                (16, 16),
                (24, 24),
                (32, 32),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            ],
        )

    return output


def build_macos() -> Path:
    """Build a macOS ICNS file from the source PNG."""
    output = BUILD.with_suffix(".icns")
    iconset = BUILD.with_suffix(".iconset")

    if iconset.exists():
        shutil.rmtree(iconset)

    iconset.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as source:
        source = source.convert("RGBA")

        for size in (16, 32, 128, 256, 512):
            source.resize(
                (size, size),
                Image.Resampling.LANCZOS,
            ).save(iconset / f"icon_{size}x{size}.png")

            source.resize(
                (size * 2, size * 2),
                Image.Resampling.LANCZOS,
            ).save(iconset / f"icon_{size}x{size}@2x.png")

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(output)],
        check=True,
    )

    shutil.rmtree(iconset)

    return output


def build_linux() -> Path:
    """Copy the source PNG to the Linux build directory."""
    output = BUILD.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, output)
    return output


def main() -> None:
    """Build the icon appropriate for the current operating system."""
    require_source()

    system = platform.system()

    if system == "Windows":
        output = build_windows()
    elif system == "Darwin":
        output = build_macos()
    elif system == "Linux":
        output = build_linux()
    else:
        raise SystemExit(f"Unsupported platform: {system}")

    print(f"Built icon: {output}")


if __name__ == "__main__":
    main()
