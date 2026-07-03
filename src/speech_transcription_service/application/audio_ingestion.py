from dataclasses import dataclass
from pathlib import Path

from speech_transcription_service.domain.audio import (
    AudioInspection,
    AudioProbe,
)
from speech_transcription_service.domain.errors import (
    UnsupportedMediaTypeError,
)

SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
    }
)

ALLOWED_NON_AUDIO_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "video/mp4",
        "video/webm",
    }
)


@dataclass(frozen=True, slots=True)
class StagedUpload:
    path: Path
    filename: str
    content_type: str | None
    size_bytes: int
    sha256: str


def validate_upload_metadata(
    filename: str | None,
    content_type: str | None,
) -> None:
    if not filename:
        raise UnsupportedMediaTypeError("The uploaded file must include a filename.")

    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise UnsupportedMediaTypeError(
            f"Unsupported file extension '{extension or '[none]'}'. "
            f"Supported extensions: {supported}."
        )

    normalized_content_type = _normalize_content_type(content_type)

    if normalized_content_type is None:
        return

    if normalized_content_type.startswith("audio/"):
        return

    if normalized_content_type in ALLOWED_NON_AUDIO_CONTENT_TYPES:
        return

    raise UnsupportedMediaTypeError(f"Unsupported content type '{normalized_content_type}'.")


def _normalize_content_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None

    normalized = content_type.split(";", maxsplit=1)[0].strip().lower()
    return normalized or None


class AudioIngestionService:
    def __init__(self, probe: AudioProbe) -> None:
        self._probe = probe

    def inspect(self, upload: StagedUpload) -> AudioInspection:
        media = self._probe.inspect(upload.path)

        return AudioInspection(
            filename=upload.filename,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            container_format=media.container_format,
            duration_seconds=media.duration_seconds,
            codec_name=media.codec_name,
            sample_rate_hz=media.sample_rate_hz,
            channels=media.channels,
            channel_layout=media.channel_layout,
            bit_rate_bps=media.bit_rate_bps,
        )
