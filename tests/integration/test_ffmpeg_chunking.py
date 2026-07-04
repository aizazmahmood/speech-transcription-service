from pathlib import Path

import pytest

from speech_transcription_service.domain.chunking import AudioChunk
from speech_transcription_service.domain.errors import (
    AudioChunkExtractionError,
    MediaDependencyUnavailableError,
)
from speech_transcription_service.infrastructure.audio.ffmpeg_chunking import (
    FFmpegAudioChunkExtractor,
)
from speech_transcription_service.infrastructure.audio.ffprobe import (
    FFprobeAudioProbe,
)
from tests.audio_fixtures import create_wave_bytes


def create_test_chunk() -> AudioChunk:
    return AudioChunk(
        index=0,
        start_seconds=0.5,
        end_seconds=1.25,
        keep_start_seconds=0.5,
        keep_end_seconds=1.25,
    )


def test_ffmpeg_extracts_normalized_audio_chunk(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "normalized-source.wav"
    destination_path = tmp_path / "chunks" / "chunk-0000.wav"

    source_path.write_bytes(
        create_wave_bytes(
            duration_seconds=2.0,
            sample_rate_hz=44_100,
            channels=2,
        )
    )

    extractor = FFmpegAudioChunkExtractor(
        timeout_seconds=10.0,
        sample_rate_hz=16_000,
        channels=1,
    )

    result_path = extractor.extract(
        source_path=source_path,
        chunk=create_test_chunk(),
        destination_path=destination_path,
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
        0.75,
        abs=0.03,
    )


def test_ffmpeg_chunk_extractor_rejects_invalid_media(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "invalid.wav"
    destination_path = tmp_path / "chunk.wav"

    source_path.write_text(
        "This is not audio.",
        encoding="utf-8",
    )

    extractor = FFmpegAudioChunkExtractor(
        timeout_seconds=5.0,
    )

    with pytest.raises(AudioChunkExtractionError):
        extractor.extract(
            source_path=source_path,
            chunk=create_test_chunk(),
            destination_path=destination_path,
        )

    assert destination_path.exists() is False


def test_ffmpeg_chunk_extractor_rejects_missing_source(
    tmp_path: Path,
) -> None:
    extractor = FFmpegAudioChunkExtractor(
        timeout_seconds=5.0,
    )

    with pytest.raises(
        AudioChunkExtractionError,
        match="source audio file does not exist",
    ):
        extractor.extract(
            source_path=tmp_path / "missing.wav",
            chunk=create_test_chunk(),
            destination_path=tmp_path / "chunk.wav",
        )


def test_ffmpeg_chunk_extractor_reports_missing_executable(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.wav"
    destination_path = tmp_path / "chunk.wav"

    source_path.write_bytes(
        create_wave_bytes(
            duration_seconds=2.0,
        )
    )

    extractor = FFmpegAudioChunkExtractor(
        executable="ffmpeg-executable-that-does-not-exist",
    )

    with pytest.raises(MediaDependencyUnavailableError):
        extractor.extract(
            source_path=source_path,
            chunk=create_test_chunk(),
            destination_path=destination_path,
        )

    assert destination_path.exists() is False
