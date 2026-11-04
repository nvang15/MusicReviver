# MusicReviver

[![CI](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml/badge.svg)](https://github.com/nvang15/MusicReviver/actions/workflows/ci.yml)

MusicReviver is a local, AI-assisted music restoration and reconstruction application intended to improve the perceived recording quality of older audio while respecting the musicians' original performances.

> **Status:** Milestones 1–12 are complete. MusicReviver provides a resumable end-to-end backend workflow, native PySide6 desktop interface, audio export, and a non-destructive stem review workspace.

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
- **Milestone 6 — Mixing / recombination (complete):** bounded reference-aware stem gains, safe floating-point summing, and objective comparison.
- **Milestone 7 — Mastering (complete):** bounded, measurement-guided stereo mastering with archival, balanced, and modern modes.
- **Milestone 8 — End-to-end pipeline orchestration (complete):** resumable, configuration-aware coordination of every backend stage.
- **Milestone 9 — PySide6 desktop GUI (complete):** native task selection, background processing, progress, cancellation, results, and safe export.
- **Milestone 10 — Windows packaging (complete):** PyInstaller onedir builds with external writable data and bundled FFmpeg tools.
- **Milestone 11 — Audio export and packaged separation reliability (complete):** staged conversion and dependable canonical packaged output.
- **Milestone 12 — Stem Review Workspace (complete):** synchronized audition, seeking, solo/mute, display labels, advisory activity detection, grouping, and grouped export.
- **Milestone 13 — Installer / distribution polish.**
- **Milestone 14 — Section refinement:** region selection, alternate separation candidates, assignment, crossfades, and undo.
- **Milestone 15 — Advanced reconstruction:** explicit, opt-in experimental instrument enhancement.

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

## Milestone 6 mixing / recombination

MusicReviver can recombine arbitrary canonical stems into a coherent stereo mix while
preserving their timing, channel relationships, and phase. In automatic mode it
prefers a valid restored set and otherwise uses separated stems. It never starts AI
separation merely because mixing was requested.

```powershell
python app.py mix "input/song.mp3"
python app.py mix "input/song.mp3" --source restored
python app.py mix "input/song.mp3" --source separated --force
```

The original standardized mix is used only as an objective reference. MusicReviver
solves a bounded least-squares problem that estimates one gain per stem while limiting
every automatic adjustment to ±3 dB. If fitting is unavailable or unsafe, unity gain
is the deterministic fallback. Stems are never individually normalized.

After floating-point summing, global attenuation is applied only when necessary to
keep the result below -0.5 dBFS. This safety gain can only reduce level; it is not a
limiter, loudness target, or mastering operation. Reports include reference, premix,
and final LUFS, RMS, peak, waveform correlation, and normalized error as descriptive
diagnostics rather than subjective quality claims.

Final output remains 48 kHz, stereo, 24-bit PCM WAV under `output/<project>/mix/`.
The engine does not time-shift, resample, invert polarity, widen stereo, add effects,
or perform mastering. A future PySide6 desktop interface can call the same structured
Python API as part of a simple Restore / Modernize workflow.

## Milestone 7 — Mastering

Mastering consumes an existing valid Milestone 6 mix and never starts import,
separation, restoration, or mixing automatically. The default `balanced` mode applies
moderate polish only when measurements justify it. `archival` prioritizes maximum
preservation and generous headroom; `modern` permits somewhat stronger—but still
bounded—gain, broad EQ, compression, and peak control.

```powershell
python app.py master "input/song.mp3"
python app.py master "input/song.mp3" --mode archival
python app.py master "input/song.mp3" --mode modern --force
```

Loudness ranges are guidance, not guaranteed targets: archival uses -20 to -16 LUFS,
balanced uses -16 to -13 LUFS, and modern uses -13 to -10 LUFS. Preservation and
sample-peak headroom always take priority. Automatic gain boosts are capped at 1, 3,
and 5 dB respectively, and an already-loud master is not amplified merely to reach a
target. Output ceilings are -1.5, -1.0, and -0.8 dBFS sample peak; reports label these
as sample peaks rather than claiming true-peak measurement.

EQ is optional broad peaking EQ, limited to ±0.5, ±1.0, or ±1.5 dB and biased toward
cuts. Stereo-linked bus compression is optional, has no makeup gain, preserves channel
relationships, and is limited to low ratios (at most 1.2:1, 1.5:1, or 1.8:1). Final
peak protection is deterministic attenuation only. Excessive reduction lowers the
achieved loudness and generates a warning instead of crushing transients.

This milestone intentionally includes no saturation, multiband compression, stereo
widening, mid/side enhancement, clipping, or streaming-platform presets. Masters and
strict JSON/text reports are staged together under `output/<project>/master/`; output
remains 48 kHz stereo 24-bit PCM WAV. The same typed API is directly callable by a
future GUI.

## Milestone 8 — End-to-End Pipeline

The `modernize` command coordinates the existing backend APIs in order without
duplicating their processing logic:

```text
import → separation → analysis → restoration → mixing → mastering
```

Run the default pipeline or select existing backend options:

```powershell
python app.py modernize "input/song.mp3"

python app.py modernize "input/song.mp3" `
  --restoration balanced `
  --mastering modern

python app.py modernize "input/song.mp3" `
  --model "UVR-MDX-NET-Inst_HQ_5.onnx" `
  --device auto `
  --mastering balanced

python app.py modernize "input/song.mp3" --force
```

Normal execution is resumable. Each input is identified by a SHA-256 content hash,
and every stage has a dependency fingerprint plus output validation. A valid stage is
reused only when both its fingerprint and its published files remain compatible.
Changing the separation model reruns separation and everything downstream; changing
restoration strength reruns restoration, mixing, and mastering; changing mastering
mode reruns mastering only. Device selection is deliberately excluded from output
invalidation because it does not change the requested separation semantics. Existing
model-aware compatibility checks still decide whether CPU or DirectML can be used.

`--force` reruns all stages. Individual backend modules retain their staged replacement
behavior, so an existing valid stage remains available if its replacement fails.
Pipeline failure stops all downstream work and records the failed/skipped states.
Cancellation can be requested through the Python API and is checked between stages;
hard termination of an active AI inference is intentionally deferred.

Pipeline state and a readable report are stored in
`output/<project>/pipeline/pipeline.json` and `pipeline.txt`. The structured result
also exposes the canonical source, arbitrary discovered stems, analysis reports,
restored stems, mix, and finished master under `output/<project>/master/`. Stem names
are discovered dynamically, so six-stem, two-stem, and future model layouts follow
the same workflow.

The PySide6 application calls the same `src.pipeline.modernize` Python API.
Progress is delivered as typed events rather than console text, and no GUI dependency
or global mutable pipeline state is present in the core orchestrator.

## Milestone 9 — Desktop GUI

Install the declared dependencies and launch the native application:

```powershell
python -m pip install -r requirements.txt
python gui.py
```

Choose or drag in a supported audio/video file, select a task, configure the visible
options, and choose **Start Processing**. The primary tasks are Separate Instruments,
Analyze Recording, Restore Stems, and Modernize Recording. Modernize is the default
and runs the complete Milestone 8 pipeline. Mixing and mastering remain backend stages
of that approachable workflow rather than requiring separate primary-task controls.

Model and device selectors use the existing separation registry and compatibility
metadata. Restoration offers Light, Balanced, and Strong. Mastering offers Archival,
Balanced, and Modern with preservation-focused descriptions. Restore Stems does not
silently run separation; missing stems produce a message directing the user to Separate
Instruments or Modernize Recording.

Processing runs on a Qt worker thread so the interface remains responsive. Typed
pipeline progress events are bridged to the UI with Qt signals. Indeterminate progress
is displayed when a backend does not expose a real percentage. Cancellation is checked
between stages, and the interface explicitly states that the active stage must finish
first.

Results list arbitrary generated stem names and relevant report/output paths. **Open
Output Folder** uses the platform-native folder opener. **Export Result…** opens a
file selection, destination, and audio format dialog. Modernize initially selects the
final master; individual stems, restored stems, and the mix can also be selected.
Analysis reports remain plain file copies. Internal `output/<project>/` files stay in
place. Existing destination filenames receive a numbered suffix.

The GUI contains no audio processing algorithms and does not use the CLI parser. It
calls the same backend and orchestration Python APIs as the command-line interface.
Audio playback, waveform display, loudness-matched A/B comparison, and installer polish
are deferred to later milestones.

## Milestone 10 — Windows Packaging

MusicReviver provides a PyInstaller `onedir` build that launches the existing dark
PySide6 GUI without requiring an installed Python interpreter or a repository checkout.
Build prerequisites are Windows, Python 3.11, project/build dependencies, and local
`ffmpeg.exe` plus `ffprobe.exe` binaries.

```powershell
py -3.11 -m pip install -r requirements-build.txt
py -3.11 packaging\build_windows.py --clean
```

The release executable is created at:

```text
dist\MusicReviver\MusicReviver.exe
```

Release builds are windowed and do not open a console. A diagnostic build retains a
console and enables PyInstaller bootloader diagnostics:

```powershell
py -3.11 packaging\build_windows.py --clean --debug
```

The build helper locates FFmpeg through `PATH`, or through an explicitly supplied
directory, then copies both tools into the distribution:

```powershell
$env:MUSICREVIVER_FFMPEG_DIR = "C:\path\to\ffmpeg\bin"
py -3.11 packaging\build_windows.py --clean
```

Packaged applications prefer `bin\ffmpeg.exe` and `bin\ffprobe.exe`, with `PATH` as a
fallback. Writable `input`, `output`, `models`, and `temp` directories live beside the
executable and are created when absent; PyInstaller's temporary bundle directory is
never used for writable state. Source execution retains repository-local directories.

AI model weights are external and are not included by default. For a private local
smoke build only, an existing cache can be copied explicitly:

```powershell
py -3.11 packaging\build_windows.py --clean --include-model-cache
```

The helper never copies existing user `input`, `output`, or `temp` contents. `build/`,
`dist/`, media, model weights, and copied executables remain ignored by Git.

Before publicly distributing a binary, review the applicable licenses and distribution
terms for FFmpeg, PySide6/Qt, PyInstaller, audio-separator, ONNX Runtime, PyTorch, and
the other bundled dependencies. No installer, code signing, custom icon, automatic
updater, or DirectML guarantee is provided in this milestone.

## Milestone 11 — Audio Export and Full-Song Reliability

Supported input extensions are WAV, MP3, FLAC, M4A, AAC, OGG, MP4, MKV, MOV, and
WEBM, provided the installed FFmpeg can decode the file's actual codec. Import
standardizes recordings to stereo, 48 kHz, 24-bit PCM WAV. Intermediate processing
stays lossless; lossy encoding happens only when explicitly exporting.

Choose **Export Result…**, check the desired files, choose a destination and format,
then click **Export**. WAV is the default. Available formats are:

| Format | Encoding |
| --- | --- |
| WAV | 24-bit PCM |
| FLAC | Lossless, 24-bit |
| MP3 | 192, 256, or 320 kbps; default 320 |
| M4A | AAC at the selected nominal bitrate; actual bitrate depends on content |

The installed FFmpeg must provide the selected encoder. Availability is checked
in the export worker before any audio is converted; missing encoders produce a
readable error. The locally bundled FFmpeg has all four encoders. Analysis-only
exports hide audio controls and copy JSON/TXT reports without invoking FFmpeg.
Arbitrary stem names and stem counts are supported. Modernize defaults to exporting
the master, with other available results selectable. The same API can export any
existing generated mix or stem without rerunning the pipeline.

Export runs in a background Qt thread. Processing and export cannot run together.
Cancel waits for the current file, then stops before publishing the batch. All files
are staged and checked with FFprobe before publication. Collisions receive `_2`,
`_3`, etc.; existing files are never silently replaced. Failed publication rolls
back newly published files belonging to that attempt. A process/power failure during
publication can leave a subset of complete outputs. On Linux/macOS, atomic
publication requires a destination filesystem supporting hard links; Windows uses
no-replace rename and does not have that restriction. Network filesystem guarantees
depend on the filesystem implementation.

Export does not normalize, adjust stereo balance, add DSP, or intentionally resample.
Lossless output preserves canonical samples. MP3/AAC can have encoder padding and
reconstructed peak overshoots; duration validation allows codec delay, and export
does not silently lower the level to enforce the source master's peak ceiling.
Export configuration/results expose codec, duration, rate, channels, bitrate, size,
paths, and elapsed time through `src.exporting`; no extra sidecars are placed in the
user's export folder.

```python
from pathlib import Path
from src.exporting import AudioFormat, ExportConfig, export_files

result = export_files(
    (Path("output/song/master/balanced_master.wav"),),
    ExportConfig(Path("exports"), AudioFormat.MP3, bitrate_kbps=320),
)
print(result.files[0].path)
```

There is no intentional 1–5 minute song limit. AI processing time and memory depend
on duration, selected model, and device; full-song AI throughput and quality have
not yet been validated for this milestone. Synthetic export checks demonstrate
format mechanics, not restoration quality. Existing cached model files are external
under `models/`. The GUI shows the selected model/cache and primary-file presence;
this is not an integrity check. The separation backend can download missing weights
and auxiliary metadata after the user agrees to proceed. Existing model-aware
CPU/DirectML rules remain in force.

Source execution uses repository-local runtime folders. Packaged execution uses
`input/`, `output/`, `models/`, and `temp/` beside the executable, with bundled tools
under `bin/`. Restored result paths resolve against this runtime root, independent
of the launch directory. User exports may be placed in any supported writable folder.

Run headless tests without setting a persistent PowerShell `QT_QPA_PLATFORM` value;
the GUI test fixtures scope that setting themselves:

```powershell
py -3.11 -m pytest -q
py -3.11 -m scripts.validate_exports --seconds 3 --bundled-tools --report temp\export-validation.json
# Optional longer media-format checks (no AI):
py -3.11 -m scripts.validate_exports --seconds 60 180 300 --bundled-tools
```

The validation script removes its synthetic media automatically. The optional JSON
report under `temp/` is ignored. It measures source-API exports using real media
tools; it does not prove the packaged GUI or AI modernization workflow. Rebuild the
distribution to include Milestone 11 changes before doing an updated GUI smoke test.

Local validation on September 29, 2026 passed for 3-, 60-, 180-, and 300-second
synthetic stereo recordings in all four formats, including each MP3 bitrate.
FFprobe reported preserved durations, 48 kHz, and two channels. Five-minute exports
took approximately 0.18 seconds (WAV), 0.39 seconds (FLAC), 2.85–3.19 seconds (MP3),
and 3.72 seconds (AAC) on the development machine. These are encoding timings only,
not separation or modernization timings; other hardware and audio will differ.

## Milestone 12 — Stem Review Workspace

After separation, choose **Review Stems** in Results. To reopen a project without
running separation, choose the original recording and use **Review Existing Stems**.
The workspace discovers every canonical WAV dynamically; it does not assume a model
or fixed number of stems.

Playback uses one shared `QAudioSink` transport that pulls aligned 48 kHz stereo
floating-point PCM from the canonical stem files. Changing selected, soloed, or muted
membership updates the next streamed audio blocks without replacing a media source or
resetting the playhead. With no selection, all unmuted stems play. A selection limits
the mix to those stems; any Solo temporarily overrides that selection, while Mute
always excludes its stem. Selection is deliberately session-only, so reopening starts
with the unsurprising full separated mix.

On Windows, stem decoding and mixing run ahead on a bounded producer thread so the
real-time Qt callback only copies prepared bytes. The sink uses the default device's
supported 48 kHz stereo format (Float32 when available, otherwise Int16), a 250 ms
buffer, matching startup/seek prefill, and a 5 ms membership-change ramp. This trades
a small controlled response delay for protection against Python scheduling and disk
decode stalls without changing canonical audio.

The combined and per-stem waveform views use cached, bounded peak envelopes rather
than painting full-resolution samples. They share one playhead and time scale, and
clicking or dragging anywhere on a waveform seeks the global transport. The custom
waveform surface is intentionally ready for a later range-selection overlay without
implementing section refinement in this milestone.

Display labels, solo/mute state, activity measurements, seek position, and logical
groups are stored atomically under `output/<project>/workspace/`. Canonical separated
and restored WAVs are never renamed, deleted, overwritten, or destructively merged.
Group mixes use unity stem gains and attenuation only when the sum would exceed the
-0.5 dBFS safety ceiling. Existing export conversion handles WAV 24-bit, FLAC, MP3,
and M4A/AAC; display and group labels are sanitized only when creating filenames.

“Likely inactive” is a conservative advisory requiring both very low RMS and very
little active audio. It never hides or deletes a stem. Separation quality remains
model-dependent: renaming and grouping organize results but do not improve separation,
and manual listening remains important. Region selection, partial re-separation,
candidate comparison, assignment, boundary crossfades, and region undo are intentionally
deferred to Milestone 14.

## Reconstruction disclaimer

Future reconstruction features will be experimental. They may synthesize a plausible interpretation from detected timing, notes, and dynamics, but **cannot recover information that never existed in the original recording**. Reconstructed output should not be represented as an exact recovery of a lost performance.

## License

MusicReviver is available under the [MIT License](LICENSE).
