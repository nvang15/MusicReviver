# MusicReviver

MusicReviver is a local, AI-assisted music restoration and reconstruction application intended to improve the perceived recording quality of older audio while respecting the musicians' original performances.

> **Status:** Milestone 2 media ingestion is complete. MusicReviver can validate common audio and video sources and create a standardized internal WAV; enhancement and AI separation are not yet implemented.

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
- **Milestone 3 — Stem separation:** local model integration with model-independent stem handling.
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

## Reconstruction disclaimer

Future reconstruction features will be experimental. They may synthesize a plausible interpretation from detected timing, notes, and dynamics, but **cannot recover information that never existed in the original recording**. Reconstructed output should not be represented as an exact recovery of a lost performance.

## License

MusicReviver is available under the [MIT License](LICENSE).
