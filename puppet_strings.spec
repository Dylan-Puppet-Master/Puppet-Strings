"""PyInstaller build: one file per platform, named for the platform it runs on.

The app uses three Qt modules -- QtCore, QtGui and QtWidgets -- but PySide6 brings every
plugin it has, and some plugins bring whole Qt modules and system libraries with them: the
on-screen keyboard brings Qt Quick and QML, the PDF image format Qt PDF, the TLS and network
plugins Qt Network, and on Linux the GTK theme brings GTK. Those plugins are left out below,
and so is what only they needed. On Linux, where it was measured, the executable went from
133 MB to 104 MB. `tools/smoke_test.py` runs the result before a release.
"""

import fnmatch
import os
import sys
from pathlib import Path

from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_dynamic_libs

PLATFORM = {
    "win32": "windows",
    "darwin": "macos",
}.get(sys.platform, "linux")

ICON = {
    "win32": Path("build/icon.ico"),
    "darwin": Path("build/icon.icns"),
}.get(sys.platform)

# Plugins nothing here loads, matched against the bundled path with forward slashes.
UNUSED_PLUGINS = [
    "*/plugins/platforminputcontexts/*virtualkeyboard*",  # Qt Quick and QML
    "*/plugins/imageformats/*pdf*",  # Qt PDF
    "*/plugins/platformthemes/*gtk3*",  # GTK; Qt draws its own file dialogs instead
    "*/plugins/tls/*",  # Qt Network: the app talks to Google through requests
    "*/plugins/networkinformation/*",
    "*/plugins/egldeviceintegrations/*",  # embedded displays, with no desktop
    "*/plugins/generic/*",
    "*/plugins/platforms/*eglfs*",
    "*/plugins/platforms/*linuxfb*",
    "*/plugins/platforms/*vnc*",
    "*/plugins/platforms/*vkkhrdisplay*",
    "*/plugins/platforms/*minimalegl*",
]
# What those plugins brought, by name, on every platform: a library matched here is one
# only they need. `opengl32sw` is Windows' software OpenGL, which only Qt Quick draws with.
UNUSED_LIBRARIES = [
    "*Qt6Quick*",
    "*QtQuick*",
    "*Qt6Qml*",
    "*QtQml*",
    "*Qt6Pdf*",
    "*QtPdf*",
    "*Qt6VirtualKeyboard*",
    "*QtVirtualKeyboard*",
    "*Qt6Network*",
    "*QtNetwork*",
    "*Qt6EglFS*",
    "*opengl32sw*",
]
UNUSED_DATA = ["PySide6/Qt/translations/*"]  # the app is in English only

# OR-Tools on Windows loads its own DLLs -- abseil, protobuf, ortools.dll and the rest -- from
# `ortools/.libs` by path, in `ortools/__init__.py`, and quietly skips any that are missing.
# Analysis cannot see a library opened that way, so they are collected into the same folder
# here; without them the solver fails to import with "DLL load failed". Elsewhere the
# extension module links its libraries, and analysis follows the links.
ORTOOLS_DLLS = collect_dynamic_libs("ortools") if PLATFORM == "windows" else []


def _matches(dest: str, patterns: list[str]) -> bool:
    path = dest.replace(os.sep, "/").lower()  # Qt6EglFS and qt6eglfs are one library
    return any(fnmatch.fnmatch(path, pattern.lower()) for pattern in patterns)


def _only_needed(binaries: list) -> list:
    """Linux: drop system libraries at the top of the bundle that nothing left needs.

    PyInstaller collects a plugin's system libraries beside it, and they stay when the plugin
    goes. A library is kept when an extension module, a plugin or a library already kept
    links it. Only shared libraries at the top of the bundle are candidates: everything in
    a package's own folder is that package's business; a Python extension module there
    (`_cffi_backend`, which signing in to Google needs) is imported, which no link shows;
    and on Windows and macOS libraries are also loaded by name, which linking cannot show.
    """
    by_name: dict[str, list[str]] = {}  # a library may be bundled in more than one place
    for dest, _, _ in binaries:
        by_name.setdefault(os.path.basename(dest), []).append(dest)
    source = {dest: src for dest, src, _ in binaries}
    candidates = {
        dest
        for dest, _, kind in binaries
        if kind == "BINARY" and os.sep not in dest and "/" not in dest
    }
    candidates = {d for d in candidates if not os.path.basename(d).startswith("libpython")}
    keep, todo = set(), [dest for dest in source if dest not in candidates]
    while todo:
        dest = todo.pop()
        if dest in keep:
            continue
        keep.add(dest)
        try:
            imports = get_imports(source[dest])
        except Exception:  # noqa: BLE001 - what it links is unknown, so keep everything
            return binaries
        for name, _ in imports:
            todo += [d for d in by_name.get(os.path.basename(name), ()) if d not in keep]
    return [entry for entry in binaries if entry[0] in keep]


analysis = Analysis(  # noqa: F821
    ["puppet_strings/__main__.py"],
    pathex=["."],
    binaries=ORTOOLS_DLLS,
    datas=[
        ("puppet_strings/skedge/grammar.lark", "puppet_strings/skedge"),
        ("puppet_strings/training/problems", "puppet_strings/training/problems"),
        ("puppet_strings/training/data", "puppet_strings/training/data"),
    ],
    hiddenimports=[
        "puppet_strings.app.main",
        "puppet_strings.training.app",
        "ortools.sat.python.cp_model",
    ],
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.Qt3DCore",
        "PySide6.QtNetwork",
        "matplotlib",
        # optional imports of numpy and pandas that nothing here uses
        "yaml",
        "pygments",
        "jinja2",
        "IPython",
        "pytest",
        "_pytest",
        "setuptools",
        "pydoc_data",
    ],
    noarchive=False,
)

analysis.binaries = [
    entry
    for entry in analysis.binaries
    if not _matches(entry[0], UNUSED_PLUGINS) and not _matches(entry[0], UNUSED_LIBRARIES)
]
analysis.datas = [entry for entry in analysis.datas if not _matches(entry[0], UNUSED_DATA)]
if PLATFORM == "linux":
    analysis.binaries = _only_needed(analysis.binaries)

archive = PYZ(analysis.pure)  # noqa: F821

executable = EXE(  # noqa: F821
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name=f"puppet-strings-{PLATFORM}",
    # A windowed Windows executable has no output, and an uncaught error there opens a
    # dialog that waits for a click, which on CI never comes. A console one that hides its
    # own window prints to a terminal it was started from and opens only the app otherwise.
    console=PLATFORM == "windows",
    hide_console="hide-early" if PLATFORM == "windows" else None,
    onefile=True,
    strip=PLATFORM == "linux",  # macOS libraries are signed, and stripping breaks that
    upx=False,
    icon=str(ICON) if ICON else None,
)
