"""Optional real-media validation; never invoked by normal CI.

Run from the repository: python -m scripts.validate_exports --seconds 3 --bundled-tools
All generated media is scoped to a temporary directory and removed on completion.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from src.config import PROJECT_ROOT, TEMP_DIR
from src.exporting import AudioFormat, ExportConfig, available_formats, export_files
from src.runtime import resolve_executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, nargs="+", default=[3])
    parser.add_argument("--bundled-tools", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if any(value <= 0 for value in args.seconds):
        parser.error("Durations must be positive")
    original_path = os.environ.get("PATH", "")
    try:
        if args.bundled_tools:
            directory = PROJECT_ROOT / "dist" / "MusicReviver" / "bin"
            if not all((directory / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")):
                parser.error("Build the Windows distribution first to validate its bundled tools")
            os.environ["PATH"] = str(directory) + os.pathsep + original_path
        formats = available_formats()
        rows = []
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="export-validation-", dir=TEMP_DIR) as temporary:
            root = Path(temporary)
            for seconds in args.seconds:
                source = root / f"synthetic-{seconds}s.wav"
                rng = np.random.default_rng(1729)
                with sf.SoundFile(source, "w", samplerate=48000, channels=2, subtype="PCM_24") as handle:
                    for second in range(seconds):
                        t = np.arange(48000) / 48000 + second
                        noise = rng.uniform(-.015, .015, (48000, 2))
                        signal = np.column_stack((.25*np.sin(2*np.pi*440*t) + .09*np.sin(2*np.pi*1234*t),
                                                  .22*np.sin(2*np.pi*550*t) + .08*np.sin(2*np.pi*1876*t)))
                        handle.write(signal + noise)
                for kind in formats:
                    for bitrate in ((192, 256, 320) if kind is AudioFormat.MP3 else (320,)):
                        result = export_files((source,), ExportConfig(root / f"{seconds}-{kind.value}-{bitrate}", kind, bitrate))
                        item = result.files[0]
                        decoded = root / "decoded.wav"
                        subprocess.run([resolve_executable("ffmpeg"), "-v", "error", "-nostdin", "-i", str(item.path),
                                        "-c:a", "pcm_f32le", "-y", str(decoded)], check=True,
                                       shell=False, capture_output=True)
                        peak = max(float(np.max(np.abs(block))) for block in sf.blocks(decoded, blocksize=48000))
                        row = asdict(item)
                        row.update(source=str(source.name), path=str(item.path.name), format=kind.value,
                                   requested_bitrate_kbps=bitrate if kind in (AudioFormat.MP3, AudioFormat.M4A) else None,
                                   input_seconds=seconds, elapsed_seconds=round(result.elapsed_seconds, 3),
                                   decoded_sample_peak_dbfs=round(float(20*np.log10(peak)), 3))
                        rows.append(row)
        report = dict(ffmpeg=resolve_executable("ffmpeg"), ffprobe=resolve_executable("ffprobe"), exports=rows,
                      note="Source API with real tools; this does not validate the packaged GUI or AI pipeline.")
        text = json.dumps(report, indent=2, allow_nan=False)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text + "\n", encoding="utf-8")
        print(text)
    finally:
        os.environ["PATH"] = original_path


if __name__ == "__main__":
    main()
