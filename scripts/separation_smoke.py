"""Explicit offline, three-second separation diagnostic; never runs in CI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--null-streams", action="store_true")
    parser.add_argument("--initialize-only", action="store_true")
    parser.add_argument("--probe-download-progress", action="store_true",
                        help="test downloader progress with a fake HTTP response; no network or model data")
    parser.add_argument("--repair-streams", action="store_true")
    parser.add_argument("--canonical", action="store_true", help="also exercise the normal stage's canonical publication")
    parser.add_argument("--check-export-dialog", action="store_true", help="construct the real export dialog offscreen using generated stems")
    args = parser.parse_args()
    cache = args.cache.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    def inventory():
        return {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in cache.iterdir() if p.is_file()}
    before = inventory()
    report = dict(cache=str(cache), before=before, frozen=bool(getattr(sys, "frozen", False)),
                  stdout_none=sys.stdout is None, stderr_none=sys.stderr is None,
                  original_stdout_none=sys.__stdout__ is None, original_stderr_none=sys.__stderr__ is None)
    def no_network(event, arguments):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("Network blocked by offline separation diagnostic")
    sys.addaudithook(no_network)
    try:
        if args.null_streams:
            sys.stdout = sys.stderr = None
        report["simulated_null_streams"] = args.null_streams
        if args.repair_streams:
            from src.runtime import initialize_standard_streams
            initialize_standard_streams()
        import numpy as np
        import soundfile as sf
        from src.runtime import configure_bundled_tools_path
        configure_bundled_tools_path()
        from src.separation.backends import AudioSeparatorBackend, DeviceMode
        from src.separation.models import get_model
        # Force this explicit cache, avoiding the library's environment override.
        import os
        os.environ["AUDIO_SEPARATOR_MODEL_DIR"] = str(cache)
        if args.initialize_only or args.probe_download_progress:
            from audio_separator.separator import Separator
            separator = Separator(model_file_dir=str(cache), output_dir=str(output / "stems"))
            report["effective_cache"] = separator.model_file_dir
            if args.probe_download_progress:
                from unittest.mock import patch
                response = type("FakeResponse", (), {"status_code": 200, "headers": {"content-length": "1"},
                    "iter_content": lambda self, **kwargs: iter((b"x",))})()
                with patch("requests.get", return_value=response):
                    separator.download_file_if_not_exists("https://invalid.local/never-requested", str(output / "fake-response.bin"))
        else:
            samples = np.arange(144000) / 48000
            audio = np.column_stack((.15*np.sin(2*np.pi*440*samples), .12*np.sin(2*np.pi*550*samples)))
            source = output / "synthetic.wav"
            sf.write(source, audio, 48000, subtype="PCM_24")
            backend = AudioSeparatorBackend(device=DeviceMode.CPU, model_cache=cache)
            if args.canonical:
                from src.separation.separator import prepare_separation, separate
                request = prepare_separation(source, model_id="htdemucs_6s.yaml", device=DeviceMode.CPU)
                stems = separate(request, backend=backend, output_root=output / "output",
                                 project_root=output, temp_root=output / "temp").stems
            else:
                stems = backend.separate(source, output / "stems", get_model("htdemucs_6s.yaml"))
            report["stems"] = {str(name): dict(path=str(path), frames=sf.info(path).frames,
                samplerate=sf.info(path).samplerate, channels=sf.info(path).channels,
                bytes=path.stat().st_size) for name, path in stems.items()}
            if args.check_export_dialog:
                from src.gui.app import create_application
                from src.gui.models import GuiResult, GuiTask
                from src.gui.export_dialog import ExportDialog
                previous_platform = os.environ.get("QT_QPA_PLATFORM")
                os.environ["QT_QPA_PLATFORM"] = "offscreen"
                try:
                    application = create_application(["offline-export-dialog-check"])
                    result = GuiResult(GuiTask.SEPARATE, "synthetic", 0., None,
                                       tuple(stems.values()), output, "Complete")
                    dialog = ExportDialog(result, str(output / "exports"))
                    report["export_dialog"] = dict(selected_files=len(dialog.selected_files()),
                        audio_controls_visible=not dialog.format.isHidden(),
                        formats=[dialog.format.itemText(i) for i in range(dialog.format.count())])
                    dialog.close()
                finally:
                    if previous_platform is None:
                        os.environ.pop("QT_QPA_PLATFORM", None)
                    else:
                        os.environ["QT_QPA_PLATFORM"] = previous_platform
        report["success"] = True
    except Exception:
        report["success"] = False
        report["traceback"] = traceback.format_exc()
    finally:
        report["after"] = inventory()
        report["cache_unchanged"] = before == report["after"]
        report["elapsed_seconds"] = time.perf_counter() - started
        (output / "diagnostic.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
