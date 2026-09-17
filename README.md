# MusicReviver

[![CI](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml/badge.svg)](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml)

MusicReviver is a local, AI-assisted music restoration and reconstruction application intended to improve the perceived recording quality of older audio while respecting the musicians' original performances.

> **Status:** Milestones 1–3 are complete. MusicReviver provides validated media import and real, local AI stem separation through `audio-separator`.

## Goals

- Accept common audio and video sources and extract usable audio.
- Separate a recording into a flexible set of musical stems.
- Analyze and restore each instrument according to its characteristics.
- Offer instrument-specific controls before remixing and mastering.
- Provide meaningful before/after comparison.
- Support explicitly enabled, experimental reconstruction for selected instruments.

## Performance preservation

The guiding rule is **preserve the performance**. Restoration should not silently replace timing, phrasing, pitch, articulation, dynamics, or human imperfections. Any future reconstruction that can alter those qualities will be explicit and opt-in.

## Planned pipeline

1. Import audio or video and extract audio when needed.
2. Separate the recording into available stems using an AI model.
3. Analyze each stem for instrument-appropriate restoration.
4. Apply user-controlled restoration and optional reconstruction.
5. Remix the processed stems.
6. Master and export the result.
7. Compare the original and restored versions.

No separation or restoration model is included in Milestone 1.

## Planned stem support

The initial target is a six-stem model:

- Vocals
- Drums
- Bass
- Guitar
- Piano / keys
- Other

The internal stem representation is intentionally open-ended. Later versions may add organ, synthesizer, electric piano, strings, brass, percussion, and other specialized instruments without assuming that every model produces exactly six stems.

## Local-first and privacy

MusicReviver is designed around local processing. User recordings should remain on the user's machine unless they deliberately choose otherwise. Copyrighted music, user recordings, generated stems, downloaded model weights, temporary audio, and large media files must never be committed to this repository.

## Roadmap

- **Milestone 1 — Foundation (complete):** repository structure, configuration, environment checks, logging utilities, extensible stem model, and tests.
- **Milestone 2 — Media ingestion (complete):** validated imports, FFmpeg conversion, output verification, and metadata inspection.
- **Milestone 3 — Stem separation (complete):** real local inference, model-aware CPU/DirectML selection, diagnostics, staged output validation, and model-independent stem handling.
- **Milestone 4 — Analysis and restoration:** per-stem diagnostics and conservative restoration tools.
- **Milestone 5 — Mixing and mastering:** user controls, remixing, mastering, and comparison.
- **Later — Experimental reconstruction:** opt-in, instrument-specific reconstruction workflows.

## Requirements

- Python 3.11
- FFmpeg and FFprobe available on `PATH`
- `pip` for installing the test dependency

MusicReviver has no third-party runtime Python dependencies. `pytest` is used for development testing.

## Development setup

From PowerShell in the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
python -m pytest
```

If PowerShell blocks activation, the environment's Python can be invoked directly as `.\.venv\Scripts\python.exe`.

## Continuous integration

Pull requests targeting `main` and pushes to `main` are automatically validated on
Ubuntu with Python 3.11. CI runs the pytest suite and Python compilation checks,
verifies FFmpeg and FFprobe availability, runs the application environment check,
and rejects accidentally tracked media, models, stems, or temporary runtime files.

## Milestone 1 functionality

The current application performs startup checks for:

- Python 3.11
- FFmpeg availability
- FFprobe availability
- Required local project directories

It reports expected missing dependencies as readable failures rather than uncaught tracebacks. The repository also includes reusable logging setup, safe directory helpers, an extensible `StemType`, and unit tests that require no audio files.

## Milestone 2 media import

Supported audio formats are WAV, MP3, FLAC, M4A, AAC, and OGG. Supported video
containers are MP4, MKV, MOV, and WebM. Video input must contain an audio stream.

Every accepted source is converted without aesthetic processing to MusicReviver's
internal format: a 48 kHz, stereo, 24-bit little-endian PCM WAV. The source file is
never modified. Conversion does **not** enhance, restore, normalize, separate, EQ,
compress, or master the audio.

Import media from the repository root:

```powershell
python app.py import "input/song.mp3"
python app.py import "input/live performance.mp4"
python app.py import "input/song.mp3" --force
```

An import creates `output/<safe-project-name>/source/original_48k.wav` and
`metadata.json`. Existing converted audio is protected unless `--force` is supplied.
Running `python app.py` with no command still performs the Milestone 1 environment
check.

## Milestone 3 AI stem separation

MusicReviver performs local AI separation through a backend-neutral interface backed
initially by `audio-separator` 0.47.0. Input media is automatically standardized by
the Milestone 2 pipeline before inference. Models are downloaded on first use into
the local `models/` cache and remain excluded from Git.

The default `htdemucs_6s.yaml` model runs on CPU and produces:

- Vocals
- Drums
- Bass
- Guitar
- Piano / keys
- Other

Piano/keys separation quality can vary significantly and is considered experimental.
The internal stem and model representations also accept arbitrary future stem sets,
including organ, synth, electric piano, strings, brass, and percussion.

The specialized `UVR-MDX-NET-Inst_HQ_5.onnx` model produces vocals and instrumental
stems and supports both CPU and optional DirectML execution. DirectML was successfully
tested during development on an AMD RX 9070 XT; this does not guarantee compatibility
with every AMD GPU or Windows configuration.

Device selection supports `auto`, `directml`, and `cpu` and is model-aware:

- `htdemucs_6s.yaml` supports CPU; automatic mode will not select DirectML.
- `UVR-MDX-NET-Inst_HQ_5.onnx` supports CPU and DirectML; automatic mode prefers
  DirectML only when ONNX Runtime exposes `DmlExecutionProvider`.
- An incompatible explicit device request fails instead of silently falling back.

CPU remains available without DirectML. DirectML requires a compatible Windows setup
and optional DirectML packages. The architecture permits a future WinML mode without
redesigning models or callers.

Inspect installed packages, providers, cached models, and compatibility:

```powershell
python app.py separation-info
```

Run six-stem CPU separation or specialized MDX separation:

```powershell
python app.py separate "input/song.mp3"
python app.py separate "input/song.mp3" --model htdemucs_6s.yaml --device cpu
python app.py separate "input/song.mp3" --model UVR-MDX-NET-Inst_HQ_5.onnx --device auto
python app.py separate "input/song.mp3" --model UVR-MDX-NET-Inst_HQ_5.onnx --device directml
```

Canonical WAV stems and `separation.json` are written beneath
`output/<project>/stems/`. Existing results are protected unless `--force` is used.
Forced replacement is staged and removes stale stems when switching models.
Separator models may operate or initially export at their native sample rate, such as
44.1 kHz. MusicReviver converts every final canonical stem to 48 kHz, stereo, 24-bit
little-endian PCM WAV for consistent downstream processing.

## Reconstruction disclaimer

Future reconstruction features will be experimental. They may synthesize a plausible interpretation from detected timing, notes, and dynamics, but **cannot recover information that never existed in the original recording**. Reconstructed output should not be represented as an exact recovery of a lost performance.

## License

MusicReviver is available under the [MIT License](LICENSE).
