import math
import struct
import wave
from pathlib import Path

import pytest

from speech_transcription_service.domain.errors import (
    InvalidAudioError,
    MediaDependencyUnavailableError,
)
from speech_transcription_service.infrastructure.audio.ffprobe import (
    FFprobeAudioProbe,
)


def create_test_wave(
    path: Path,
    duration_seconds: float = 0.25,
    sample_rate_hz: int = 16_000,
) -> None:
    frame_count = int(duration_seconds * sample_rate_hz)
    frames = bytearray()

    for index in range(frame_count):
        sample = int(12_000 * math.sin(2 * math.pi * 440 * index / sample_rate_hz))
        frames.extend(struct.pack("<h", sample))

    with wave.open(str(path), "wb") as audio_file:
        audio_file.setnchannels(1)
        audio_file.setsampwidth(2)
        audio_file.setframerate(sample_rate_hz)
        audio_file.writeframes(bytes(frames))


def test_ffprobe_reads_real_audio_metadata(tmp_path: Path) -> None:
    audio_path = tmp_path / "tone.wav"
    create_test_wave(audio_path)

    probe = FFprobeAudioProbe(timeout_seconds=5.0)

    result = probe.inspect(audio_path)

    assert result.container_format == "wav"
    assert result.codec_name == "pcm_s16le"
    assert result.sample_rate_hz == 16_000
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.25, abs=0.02)


def test_ffprobe_rejects_a_non_media_file(tmp_path: Path) -> None:
    invalid_path = tmp_path / "not-audio.wav"
    invalid_path.write_text("This is not audio.", encoding="utf-8")

    probe = FFprobeAudioProbe(timeout_seconds=5.0)

    with pytest.raises(InvalidAudioError):
        probe.inspect(invalid_path)


def test_ffprobe_reports_a_missing_executable(tmp_path: Path) -> None:
    audio_path = tmp_path / "tone.wav"
    create_test_wave(audio_path)

    probe = FFprobeAudioProbe(executable="ffprobe-executable-that-does-not-exist")

    with pytest.raises(MediaDependencyUnavailableError):
        probe.inspect(audio_path)
