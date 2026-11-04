# -*- mode: python ; coding: utf-8 -*-
"""Canonical onedir PyInstaller definition for MusicReviver."""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, get_package_paths

spec_dir = Path(SPECPATH).resolve()
project_root = spec_dir.parent
debug_build = os.environ.get("MUSICREVIVER_BUILD_DEBUG") == "1"
diagnostic_build = os.environ.get("MUSICREVIVER_BUILD_DIAGNOSTICS") == "1"
_, separator_package = get_package_paths("audio_separator")
# The cached checkpoint names demucs.htdemucs. audio-separator exposes this
# vendored package through sys.path before torch unpickles the model.
vendored_modules = Path(separator_package) / "separator" / "uvr_lib_v5"

analysis = Analysis(
    [str(project_root / "gui.py"),
     *([str(project_root / "scripts/separation_smoke.py")] if diagnostic_build else [])],
    pathex=[str(project_root), str(vendored_modules)],
    binaries=[],
    # Read through importlib.resources during model registry/hash lookup.
    datas=collect_data_files("audio_separator", includes=["models-scores.json", "models.json", "model-data.json"]),
    # These registered architectures are loaded through importlib.import_module.
    hiddenimports=["audio_separator.separator",
                   "audio_separator.separator.architectures.demucs_separator",
                   "audio_separator.separator.architectures.mdx_separator",
                   "audio_separator.separator.uvr_lib_v5.demucs.htdemucs",
                   "demucs.htdemucs"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(spec_dir / "runtime_hook.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    [script for script in analysis.scripts if script[0] != "separation_smoke"],
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

diagnostics = []
if diagnostic_build:
    for name, console in (("SeparationSmokeRelease", False), ("SeparationSmokeDebug", True)):
        diagnostics.append(EXE(
            pyz, [script for script in analysis.scripts if script[0] != "gui"], [],
            exclude_binaries=True, name=name, console=console, debug=False,
            strip=False, upx=True, disable_windowed_traceback=False,
        ))

collection = COLLECT(
    executable,
    *diagnostics,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="MusicReviver",
)
