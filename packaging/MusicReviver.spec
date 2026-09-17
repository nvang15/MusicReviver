# -*- mode: python ; coding: utf-8 -*-
"""Canonical onedir PyInstaller definition for MusicReviver."""

import os
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
project_root = spec_dir.parent
debug_build = os.environ.get("MUSICREVIVER_BUILD_DEBUG") == "1"

analysis = Analysis(
    [str(project_root / "gui.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=["audio_separator.separator"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MusicReviver",
    debug=debug_build,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=debug_build,
    disable_windowed_traceback=False,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="MusicReviver",
)
