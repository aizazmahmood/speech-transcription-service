from pathlib import Path

import pytest

from speech_transcription_service.domain.errors import (
    AudioNormalizationError,
    MediaDependencyUnavailableError,
)
from speech_transcription_service.infrastructure.audio.ffmpeg import (
    FFmpegAudioNormalizer,
)
from speech_transcription_service.infrastructure.audio.ffprobe import (
    FFprobeAudioProbe,
)
from tests.audio_fixtures import create_wave_bytes


def test_ffmpeg_normalizes_audio_for_transcription(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source-stereo.wav"
    destination_path = tmp_path / "normalized.wav"

    source_path.write_bytes(
        create_wave_bytes(
            duration_seconds=0.5,
            sample_rate_hz=44_100,
            channels=2,
        )
    )

    normalizer = FFmpegAudioNormalizer(
        timeout_seconds=10.0,
        sample_rate_hz=16_000,
        channels=1,
    )

    result_path = normalizer.normalize(
        source_path,
        destination_path,
    )

    probe = FFprobeAudioProbe(timeout_seconds=5.0)
    metadata = probe.inspect(result_path)

    assert result_path == destination_path
    assert result_path.exists()
    assert source_path.exists()

    assert metadata.container_format == "wav"
    assert metadata.codec_name == "pcm_s16le"
    assert metadata.sample_rate_hz == 16_000
    assert metadata.channels == 1
    assert metadata.duration_seconds == pytest.approx(
        0.5,
        abs=0.03,
    )


def test_ffmpeg_rejects_invalid_source_media(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "invalid.mp3"
    destination_path = tmp_path / "normalized.wav"

    source_path.write_text(
        "This is not an audio file.",
        encoding="utf-8",
    )

    normalizer = FFmpegAudioNormalizer(
        timeout_seconds=5.0,
    )

    with pytest.raises(AudioNormalizationError):
        normalizer.normalize(
            source_path,
            destination_path,
        )

    assert destination_path.exists() is False


def test_ffmpeg_reports_a_missing_executable(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.wav"
    destination_path = tmp_path / "normalized.wav"

    source_path.write_bytes(create_wave_bytes())

    normalizer = FFmpegAudioNormalizer(
        executable="ffmpeg-executable-that-does-not-exist",
    )

    with pytest.raises(MediaDependencyUnavailableError):
        normalizer.normalize(
            source_path,
            destination_path,
        )

    assert destination_path.exists() is False
