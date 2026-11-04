# Windows packaging

MusicReviver uses a PyInstaller `onedir` build. The release spec is windowed (no
console); `--debug` enables a console and bootloader diagnostics. FFmpeg binaries and
model weights are not stored in Git or embedded in the executable.

The build helper copies locally installed `ffmpeg.exe` and `ffprobe.exe` into
`dist/MusicReviver/bin`. Set `MUSICREVIVER_FFMPEG_DIR` when they are not on `PATH`.
Local model weights are copied only with the explicit `--include-model-cache` option.

Before publicly distributing binaries, review the licenses and redistribution terms
for FFmpeg, PySide6/Qt, PyInstaller, audio-separator, ONNX Runtime, PyTorch, and all
other included dependencies. This project does not make a claim about suitability for
any particular distribution arrangement.

Windowed builds run `runtime_hook.py` before dependency imports. Only absent
`sys.stdout` / `sys.stderr` are replaced, using append-only files under external
`temp/windowed-stdout.log` and `temp/windowed-stderr.log`. Existing console or
redirected streams are preserved. This fixes Demucs/download tqdm progress writes
when the Windows GUI bootloader supplies no console streams. If the log directory
is unwritable, the missing stream uses the null device; exceptions still propagate
to the GUI's technical details through the original exception chain.

The spec explicitly collects audio-separator's `models-scores.json`, `models.json`,
and `model-data.json`, plus the dynamically loaded Demucs and MDX architecture
modules supported by MusicReviver's registry. No model weights are bundled.
The HTDemucs checkpoint also names `demucs.htdemucs` inside its pickle metadata.
The spec resolves this exact module from audio-separator's vendored `uvr_lib_v5`
directory, matching the backend's source-execution import path.
Both the qualified vendored module and the checkpoint's short import name are
collected because the frozen importer's path mapping can resolve through either.

For local diagnostics only, set `MUSICREVIVER_BUILD_DIAGNOSTICS=1` when running the
spec. It additionally creates `SeparationSmokeDebug.exe` (console) and
`SeparationSmokeRelease.exe` (windowed) sharing the GUI's dependency bundle and
runtime hook. These helpers accept `--cache <existing-cache>` and `--output <new-folder>`.
They synthesize three seconds of audio, block network connections, run CPU HTDemucs,
and save full chained tracebacks, stem details, and before/after cache hashes to
`diagnostic.json`. They never run as part of GUI startup or normal automated tests.
The source equivalent is `py -3.11 -m scripts.separation_smoke` with the same arguments.
Use a new isolated distribution directory for validation so existing runtime data
and downloaded models are preserved.
Do not run `--clean` or PyInstaller `--noconfirm` against a distribution containing
models or user outputs: PyInstaller replaces its collection directory. Use a fresh
`--distpath` for debugging an existing installation.

The offline smoke helper's `--canonical` option exercises normal stem publication;
`--check-export-dialog` constructs the export dialog offscreen with the real stems.
Neither is a full modernization or full-song quality test. GUI appearance still
requires a visible desktop check.
