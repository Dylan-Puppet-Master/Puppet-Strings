"""PyInstaller build: one file per platform, named for the platform it runs on.

    pyinstaller puppet_strings.spec

The name carries the platform because `puppet_strings.update` picks the release asset whose
name mentions the platform it is running on.
"""

import sys

PLATFORM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")

analysis = Analysis(  # noqa: F821 - PyInstaller injects these names
    ["puppet_strings/__main__.py"],
    pathex=["."],
    datas=[("puppet_strings/skedge/grammar.lark", "puppet_strings/skedge")],
    hiddenimports=["puppet_strings.app.main", "ortools.sat.python.cp_model"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "matplotlib"],
    noarchive=False,
)
archive = PYZ(analysis.pure)  # noqa: F821

executable = EXE(  # noqa: F821
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name=f"puppet-strings-{PLATFORM}",
    console=False,
    onefile=True,
    upx=False,
)
