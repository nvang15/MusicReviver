# MusicReviver

[![CI](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml/badge.svg)](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml)

MusicReviver is a local, AI-assisted music restoration and reconstruction application intended to improve the perceived recording quality of older audio while respecting the musicians' original performances.

> **Status:** Milestones 1–5 are complete. MusicReviver provides validated media import, local AI stem separation, objective audio analysis, and conservative analysis-driven stem restoration.

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
- **Milestone 4 — Audio analysis (complete):** objective full-mix and per-stem measurements for future restoration decisions.
- **Milestone 5 — Restoration (complete):** conservative, measurement-guided planning and stem processing.
- **Milestone 6 — Mixing and mastering:** user controls, remixing, mastering, and comparison.
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

## Milestone 4 audio analysis

MusicReviver can measure a standardized source and every existing canonical WAV stem
without changing their samples. Analysis does not trigger stem separation. Run:

```powershell
python app.py analyze "input/song.mp3"
python app.py analyze "input/song.mp3" --force
```

Reports are written to `output/<project>/analysis/analysis.json` and `analysis.txt`.
Existing reports are protected unless `--force` is provided, and replacement is
staged so a failed analysis does not corrupt a valid report.

### Measurements

- **Peak dBFS:** the largest absolute sample level relative to digital full scale.
- **RMS / RMS dBFS:** average signal energy across all samples and channels.
- **Integrated LUFS:** BS.1770-style program loudness when duration and signal permit.
- **Crest factor:** peak dBFS minus RMS dBFS.
- **Dynamic range estimate:** the difference between the 95th and 10th percentile
  levels of 50 ms RMS frames above -60 dBFS. This is transparent approximation, not
  an official “DR score.”
- **Spectral centroid, bandwidth, and rolloff:** power-weighted summaries of frequency
  content.
- **Frequency-band distribution:** normalized FFT power fractions for sub, bass,
  low-mid, mid, upper-mid, high, and air bands.
- **Clipping detection:** samples within 0.1 dB of digital full scale.
- **DC offset:** mean normalized sample value.
- **Stereo correlation and balance:** left/right correlation and RMS level difference
  when two usable channels are present.

### Estimates

- **Estimated noise floor:** the 10th-percentile level of active 50 ms frames. Music
  may be present in those frames, so this is not an isolated electrical-noise reading.
- **Tempo estimate:** full-mix-only onset and beat tracking result.
- **Key estimate:** experimental full-mix chroma correlation against major/minor key
  profiles, accompanied by a confidence value and uncertainty warnings.

Unavailable or unreliable measurements are stored as JSON `null` with warnings rather
than NaN or Infinity. These results are descriptive only: MusicReviver does not yet
use them to EQ, compress, normalize, restore, remix, reconstruct, or master audio.
The restoration engine consumes this structured analysis data for conservative decisions.

## Milestone 5 conservative restoration

Restoration is preservation-first and split into two layers: a planner consumes the
existing structured analysis, then a DSP processor executes only the explicit actions
in each plan. MusicReviver may intentionally choose an empty plan and publish an
unchanged canonical copy for predictable downstream mixing.

Preview decisions without changing audio:

```powershell
python app.py plan-restoration "input/song.mp3"
python app.py plan-restoration "input/song.mp3" --strength light --force
```

Restore existing separated stems:

```powershell
python app.py restore "input/song.mp3"
python app.py restore "input/song.mp3" --strength strong --force
```

Strengths are `light`, `balanced` (default), and `strong`. Strength adjusts documented
thresholds and bounded processing amounts; even strong mode remains conservative.
Every automatic action includes a reason tied to measurements in `analysis.json`.

Supported automatic actions are:

- Per-channel DC-offset removal when measured offset exceeds the selected threshold.
- Stem-aware high-pass filtering only when measured 20–60 Hz energy exceeds the
  selected threshold. Bass and drums are limited to subsonic cutoff frequencies to
  preserve fundamentals and kick energy.
- Gentle compression only when both crest factor and the dynamic-range estimate cross
  conservative thresholds.
- Safety peak protection only when planned processing approaches digital full scale;
  it is not used to increase loudness.

The DSP layer is portable NumPy/SciPy code: stable Butterworth second-order-section
filters provide high-pass cleanup, a deterministic linked-stereo envelope applies
gentle compression without makeup gain, and peak safety uses attenuation-only gain
when the configured ceiling would otherwise be exceeded. Normal-length files use
zero-phase filtering; very short files use safely initialized causal SOS filtering.

MusicReviver warns about detected clipping but does not claim to repair it. The
noise-floor value is an estimate that may contain musical material, so restoration
does not apply a hard gate or neural denoising. Stereo correlation warnings do not
trigger widening. This milestone provides no de-clipping, neural denoising, mastering,
remixing, generative reconstruction, re-synthesis, or instrument replacement.

Restored stems remain 48 kHz, stereo, 24-bit PCM WAV files under
`output/<project>/restored/`. Publication is staged so a failed stem cannot leave a
partial set, and `--force` safely replaces old results and removes stale files.

## Reconstruction disclaimer

Future reconstruction features will be experimental. They may synthesize a plausible interpretation from detected timing, notes, and dynamics, but **cannot recover information that never existed in the original recording**. Reconstructed output should not be represented as an exact recovery of a lost performance.

## License

MusicReviver is available under the [MIT License](LICENSE).
