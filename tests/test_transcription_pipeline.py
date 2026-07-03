from collections.abc import Iterator
from pathlib import Path

import pytest

from speech_transcription_service.application.transcription import (
    TranscriptionPipeline,
)
from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.errors import (
    NormalizedAudioContractError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
)


class StubAudioProbe:
    def __init__(
        self,
        results: list[ProbedAudio],
        events: list[str],
    ) -> None:
        self._results: Iterator[ProbedAudio] = iter(results)
        self._events = events
        self.paths: list[Path] = []

    def inspect(self, path: Path) -> ProbedAudio:
        self.paths.append(path)
        self._events.append(f"probe:{path.name}")
        return next(self._results)


class StubAudioNormalizer:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.source_paths: list[Path] = []
        self.destination_paths: list[Path] = []

    def normalize(
        self,
        source_path: Path,
        destination_path: Path,
    ) -> Path:
        self.source_paths.append(source_path)
        self.destination_paths.append(destination_path)

        self._events.append(f"normalize:{source_path.name}->{destination_path.name}")

        destination_path.write_bytes(b"normalized audio")
        return destination_path


class StubTranscriptionEngine:
    def __init__(
        self,
        result: TranscriptionResult,
        events: list[str],
    ) -> None:
        self._result = result
        self._events = events
        self.audio_paths: list[Path] = []
        self.options: list[TranscriptionOptions] = []

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionResult:
        self.audio_paths.append(audio_path)
        self.options.append(options)
        self._events.append(f"transcribe:{audio_path.name}")
        return self._result


def create_source_audio() -> ProbedAudio:
    return ProbedAudio(
        container_format="mp3",
        duration_seconds=8.0,
        codec_name="mp3",
        sample_rate_hz=48_000,
        channels=2,
        channel_layout="stereo",
        bit_rate_bps=192_000,
    )


def create_normalized_audio(
    sample_rate_hz: int = 16_000,
) -> ProbedAudio:
    return ProbedAudio(
        container_format="wav",
        duration_seconds=8.0,
        codec_name="pcm_s16le",
        sample_rate_hz=sample_rate_hz,
        channels=1,
        channel_layout=None,
        bit_rate_bps=256_000,
    )


def create_transcription_result() -> TranscriptionResult:
    segments = (
        TranscriptSegment(
            index=0,
            start_seconds=0.0,
            end_seconds=2.4,
            text="Hello from the transcription service.",
        ),
        TranscriptSegment(
            index=1,
            start_seconds=2.4,
            end_seconds=5.1,
            text="This result includes timestamps.",
        ),
    )

    return TranscriptionResult(
        text=" ".join(segment.text for segment in segments),
        language="en",
        language_probability=0.98,
        duration_seconds=8.0,
        segments=segments,
        model_name="stub-model",
        processing_seconds=0.12,
    )


def test_pipeline_inspects_normalizes_verifies_and_transcribes(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"source audio")

    probe = StubAudioProbe(
        results=[
            create_source_audio(),
            create_normalized_audio(),
        ],
        events=events,
    )
    normalizer = StubAudioNormalizer(events)
    engine = StubTranscriptionEngine(
        result=create_transcription_result(),
        events=events,
    )

    options = TranscriptionOptions(
        language="en",
        beam_size=3,
        vad_filter=True,
    )

    pipeline = TranscriptionPipeline(
        probe=probe,
        normalizer=normalizer,
        engine=engine,
    )

    result = pipeline.transcribe(
        source_path=source_path,
        workspace=tmp_path / "workspace",
        options=options,
    )

    assert result.source_audio.codec_name == "mp3"
    assert result.normalized_audio.codec_name == "pcm_s16le"
    assert result.transcript.language == "en"
    assert len(result.transcript.segments) == 2

    assert events == [
        "probe:source.mp3",
        "normalize:source.mp3->normalized.wav",
        "probe:normalized.wav",
        "transcribe:normalized.wav",
    ]

    assert engine.audio_paths == [tmp_path / "workspace" / "normalized.wav"]
    assert engine.options == [options]


def test_pipeline_rejects_normalized_audio_with_wrong_format(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"source audio")

    probe = StubAudioProbe(
        results=[
            create_source_audio(),
            create_normalized_audio(sample_rate_hz=44_100),
        ],
        events=events,
    )
    normalizer = StubAudioNormalizer(events)
    engine = StubTranscriptionEngine(
        result=create_transcription_result(),
        events=events,
    )

    pipeline = TranscriptionPipeline(
        probe=probe,
        normalizer=normalizer,
        engine=engine,
    )

    with pytest.raises(
        NormalizedAudioContractError,
        match="sample rate 44100 Hz",
    ):
        pipeline.transcribe(
            source_path=source_path,
            workspace=tmp_path / "workspace",
            options=TranscriptionOptions(),
        )

    assert engine.audio_paths == []
    assert "transcribe:normalized.wav" not in events


def test_transcription_options_reject_invalid_values() -> None:
    with pytest.raises(
        ValueError,
        match="Beam size must be at least one",
    ):
        TranscriptionOptions(beam_size=0)

    with pytest.raises(
        ValueError,
        match="Language must be omitted",
    ):
        TranscriptionOptions(language="   ")
