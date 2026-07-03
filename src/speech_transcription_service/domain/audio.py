from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProbedAudio:
    container_format: str
    duration_seconds: float
    codec_name: str
    sample_rate_hz: int
    channels: int
    channel_layout: str | None
    bit_rate_bps: int | None


@dataclass(frozen=True, slots=True)
class AudioInspection:
    filename: str
    content_type: str | None
    size_bytes: int
    sha256: str
    container_format: str
    duration_seconds: float
    codec_name: str
    sample_rate_hz: int
    channels: int
    channel_layout: str | None
    bit_rate_bps: int | None


class AudioProbe(Protocol):
    def inspect(self, path: Path) -> ProbedAudio:
        """Inspect a local media file and return its audio metadata."""
        ...


class AudioNormalizer(Protocol):
    def normalize(
        self,
        source_path: Path,
        destination_path: Path,
    ) -> Path:
        """Normalize audio and return the generated output path."""
        ...
