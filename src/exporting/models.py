"""Public export configuration and measured results."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AudioFormat(str, Enum):
    WAV = "wav"
    FLAC = "flac"
    MP3 = "mp3"
    M4A = "m4a"


@dataclass(frozen=True)
class ExportConfig:
    destination: Path
    format: AudioFormat = AudioFormat.WAV
    bitrate_kbps: int = 320

    def __post_init__(self):
        object.__setattr__(self, "destination", Path(self.destination).expanduser().resolve())
        object.__setattr__(self, "format", AudioFormat(self.format))
        if self.bitrate_kbps not in (192, 256, 320):
            raise ValueError("Choose 192, 256, or 320 kbps.")


@dataclass(frozen=True)
class ExportProgress:
    completed: int
    total: int
    message: str


@dataclass(frozen=True)
class ExportedFile:
    source: Path
    path: Path
    codec: str | None
    duration: float | None
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    size_bytes: int


@dataclass(frozen=True)
class ExportResult:
    files: tuple[ExportedFile, ...]
    elapsed_seconds: float
