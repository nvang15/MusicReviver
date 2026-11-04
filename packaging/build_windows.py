"""Build the Windows onedir distribution without bundling user runtime data."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "packaging" / "MusicReviver.spec"
DIST_ROOT = PROJECT_ROOT / "dist"
BUILD_ROOT = PROJECT_ROOT / "build"


class BuildError(RuntimeError):
    """Readable packaging configuration or execution failure."""


@dataclass(frozen=True)
class BuildOptions:
    clean: bool = False
    debug: bool = False
    include_model_cache: bool = False


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the MusicReviver Windows onedir application")
    parser.add_argument("--clean", action="store_true", help="remove old PyInstaller build and dist output first")
    parser.add_argument("--debug", action="store_true", help="build with a console for packaging diagnostics")
    parser.add_argument("--include-model-cache", action="store_true",
                        help="copy the local model cache for private smoke testing only")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> BuildOptions:
    args = create_parser().parse_args(argv)
    return BuildOptions(args.clean, args.debug, args.include_model_cache)


def validate_build_host() -> None:
    if sys.platform != "win32":
        raise BuildError("Windows packaging must be run on Windows.")
    if sys.version_info[:2] != (3, 11):
        raise BuildError(f"Python 3.11 is required; found {sys.version_info.major}.{sys.version_info.minor}.")


def locate_ffmpeg_directory(environment: dict[str, str] | None = None) -> Path:
    environment = environment or os.environ
    override = environment.get("MUSICREVIVER_FFMPEG_DIR")
    if override:
        directory = Path(override).expanduser().resolve()
        if all((directory / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")):
            return directory
        raise BuildError("MUSICREVIVER_FFMPEG_DIR must contain ffmpeg.exe and ffprobe.exe.")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise BuildError(
            "Could not locate ffmpeg.exe and ffprobe.exe. Install FFmpeg on PATH or set "
            "MUSICREVIVER_FFMPEG_DIR to their directory."
        )
    directories = {Path(ffmpeg).resolve().parent, Path(ffprobe).resolve().parent}
    if len(directories) != 1:
        raise BuildError("ffmpeg.exe and ffprobe.exe must come from the same directory.")
    return directories.pop()


def pyinstaller_command(options: BuildOptions) -> list[str]:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if options.clean:
        command.append("--clean")
    command.append(str(SPEC_PATH))
    return command


def build_environment(options: BuildOptions) -> dict[str, str]:
    environment = os.environ.copy()
    environment["MUSICREVIVER_BUILD_DEBUG"] = "1" if options.debug else "0"
    return environment


def prepare_distribution(distribution: Path, ffmpeg_directory: Path,
                         *, include_model_cache: bool = False) -> None:
    """Add only external tools and empty writable runtime directories."""
    if not distribution.is_dir():
        raise BuildError(f"PyInstaller output was not created: {distribution}")
    for name in ("input", "output", "models", "temp"):
        (distribution / name).mkdir(exist_ok=True)
    bin_directory = distribution / "bin"
    bin_directory.mkdir(exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        source = ffmpeg_directory / name
        if not source.is_file():
            raise BuildError(f"Required packaging tool is missing: {source}")
        shutil.copy2(source, bin_directory / name)
    if include_model_cache:
        source_models = PROJECT_ROOT / "models"
        if source_models.is_dir():
            shutil.copytree(source_models, distribution / "models", dirs_exist_ok=True)


def build(options: BuildOptions) -> Path:
    validate_build_host()
    ffmpeg_directory = locate_ffmpeg_directory()
    if options.clean:
        for target in (BUILD_ROOT, DIST_ROOT):
            if target.exists():
                shutil.rmtree(target)
    subprocess.run(pyinstaller_command(options), cwd=PROJECT_ROOT,
                   env=build_environment(options), check=True)
    distribution = DIST_ROOT / "MusicReviver"
    prepare_distribution(distribution, ffmpeg_directory,
                         include_model_cache=options.include_model_cache)
    executable = distribution / "MusicReviver.exe"
    if not executable.is_file():
        raise BuildError(f"Build completed without the expected executable: {executable}")
    return executable


def main(argv: Sequence[str] | None = None) -> int:
    try:
        executable = build(parse_args(argv))
    except (BuildError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(f"MusicReviver build complete:\n{executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
