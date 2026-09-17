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
