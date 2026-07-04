from collections.abc import Iterator
from pathlib import Path

import pytest

from speech_transcription_service.application.long_audio_transcription import (
    LongAudioTranscriptionPipeline,
)
from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.chunking import (
    AudioChunk,
    AudioChunkPlanner,
    ChunkTranscriptMerger,
)
from speech_transcription_service.domain.errors import (
    NormalizedAudioContractError,
    TranscriptionError,
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

    def inspect(
        self,
        path: Path,
    ) -> ProbedAudio:
        self._events.append(f"probe:{path.name}")
        return next(self._results)


class StubAudioChunkExtractor:
    def __init__(
        self,
        events: list[str],
    ) -> None:
        self._events = events
        self.chunks: list[AudioChunk] = []
        self.destination_paths: list[Path] = []

    def extract(
        self,
        source_path: Path,
        chunk: AudioChunk,
        destination_path: Path,
    ) -> Path:
        self.chunks.append(chunk)
        self.destination_paths.append(destination_path)

        self._events.append(f"extract:{chunk.index}:{source_path.name}")

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination_path.write_bytes(b"chunk audio")

        return destination_path


class StubTranscriptionEngine:
    def __init__(
        self,
        results: list[TranscriptionResult],
        events: list[str],
    ) -> None:
        self._results: Iterator[TranscriptionResult] = iter(results)
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

        return next(self._results)


def create_source_audio(
    duration_seconds: float = 70.0,
) -> ProbedAudio:
    return ProbedAudio(
        container_format="mp3",
        duration_seconds=duration_seconds,
        codec_name="mp3",
        sample_rate_hz=48_000,
        channels=2,
        channel_layout="stereo",
        bit_rate_bps=192_000,
    )


def create_chunk_audio(
    duration_seconds: float,
    sample_rate_hz: int = 16_000,
) -> ProbedAudio:
    return ProbedAudio(
        container_format="wav",
        duration_seconds=duration_seconds,
        codec_name="pcm_s16le",
        sample_rate_hz=sample_rate_hz,
        channels=1,
        channel_layout=None,
        bit_rate_bps=256_000,
    )


def create_result(
    segments: tuple[TranscriptSegment, ...],
    language: str | None = "en",
    language_probability: float | None = 0.9,
    model_name: str = "stub-model",
    processing_seconds: float = 0.4,
) -> TranscriptionResult:
    return TranscriptionResult(
        text=" ".join(segment.text for segment in segments),
        language=language,
        language_probability=language_probability,
        duration_seconds=30.0,
        segments=segments,
        model_name=model_name,
        processing_seconds=processing_seconds,
    )


def create_segment(
    index: int,
    start_seconds: float,
    end_seconds: float,
    text: str,
) -> TranscriptSegment:
    return TranscriptSegment(
        index=index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
    )


def test_pipeline_extracts_transcribes_merges_and_cleans_chunks(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"source audio")

    probe = StubAudioProbe(
        results=[
            create_source_audio(),
            create_chunk_audio(30.0),
            create_chunk_audio(30.0),
            create_chunk_audio(20.0),
        ],
        events=events,
    )
    extractor = StubAudioChunkExtractor(events)
    engine = StubTranscriptionEngine(
        results=[
            create_result(
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=2.0,
                        end_seconds=4.0,
                        text="First segment.",
                    ),
                    create_segment(
                        index=1,
                        start_seconds=25.0,
                        end_seconds=27.0,
                        text="Shared speech.",
                    ),
                ),
                language_probability=0.9,
                processing_seconds=0.4,
            ),
            create_result(
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=0.0,
                        end_seconds=2.0,
                        text="Shared speech.",
                    ),
                    create_segment(
                        index=1,
                        start_seconds=5.0,
                        end_seconds=7.0,
                        text="Second segment.",
                    ),
                ),
                language_probability=0.8,
                processing_seconds=0.5,
            ),
            create_result(
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=5.0,
                        end_seconds=7.0,
                        text="Third segment.",
                    ),
                ),
                language_probability=0.85,
                processing_seconds=0.3,
            ),
        ],
        events=events,
    )

    options = TranscriptionOptions(
        language=None,
        beam_size=3,
        vad_filter=True,
        word_timestamps=True,
    )

    pipeline = LongAudioTranscriptionPipeline(
        probe=probe,
        extractor=extractor,
        engine=engine,
        planner=AudioChunkPlanner(
            chunk_duration_seconds=30.0,
            overlap_seconds=5.0,
        ),
        merger=ChunkTranscriptMerger(),
    )

    result = pipeline.transcribe(
        source_path=source_path,
        workspace=tmp_path / "workspace",
        options=options,
    )

    assert [
        (
            chunk.start_seconds,
            chunk.end_seconds,
        )
        for chunk in result.chunks
    ] == [
        (0.0, 30.0),
        (25.0, 55.0),
        (50.0, 70.0),
    ]

    assert [
        (
            segment.index,
            segment.start_seconds,
            segment.end_seconds,
            segment.text,
        )
        for segment in result.transcript.segments
    ] == [
        (0, 2.0, 4.0, "First segment."),
        (1, 25.0, 27.0, "Shared speech."),
        (2, 30.0, 32.0, "Second segment."),
        (3, 55.0, 57.0, "Third segment."),
    ]

    assert result.transcript.text == (
        "First segment. Shared speech. Second segment. Third segment."
    )
    assert result.transcript.duration_seconds == 70.0
    assert result.transcript.language == "en"
    assert result.transcript.language_probability == pytest.approx(0.85)
    assert result.transcript.model_name == "stub-model"
    assert result.transcript.processing_seconds == pytest.approx(1.2)

    assert engine.options[0] == options
    assert engine.options[1:] == [
        TranscriptionOptions(
            language="en",
            beam_size=3,
            vad_filter=True,
            word_timestamps=True,
        ),
        TranscriptionOptions(
            language="en",
            beam_size=3,
            vad_filter=True,
            word_timestamps=True,
        ),
    ]

    assert all(path.exists() is False for path in extractor.destination_paths)

    assert events == [
        "probe:source.mp3",
        "extract:0:source.mp3",
        "probe:chunk-0000.wav",
        "transcribe:chunk-0000.wav",
        "extract:1:source.mp3",
        "probe:chunk-0001.wav",
        "transcribe:chunk-0001.wav",
        "extract:2:source.mp3",
        "probe:chunk-0002.wav",
        "transcribe:chunk-0002.wav",
    ]


def test_pipeline_rejects_chunk_with_invalid_audio_contract(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"source audio")

    probe = StubAudioProbe(
        results=[
            create_source_audio(duration_seconds=10.0),
            create_chunk_audio(
                duration_seconds=10.0,
                sample_rate_hz=44_100,
            ),
        ],
        events=events,
    )
    extractor = StubAudioChunkExtractor(events)
    engine = StubTranscriptionEngine(
        results=[
            create_result(segments=()),
        ],
        events=events,
    )

    pipeline = LongAudioTranscriptionPipeline(
        probe=probe,
        extractor=extractor,
        engine=engine,
        planner=AudioChunkPlanner(),
        merger=ChunkTranscriptMerger(),
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
    assert extractor.destination_paths[0].exists() is False


def test_pipeline_rejects_inconsistent_model_names(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"source audio")

    probe = StubAudioProbe(
        results=[
            create_source_audio(duration_seconds=35.0),
            create_chunk_audio(30.0),
            create_chunk_audio(10.0),
        ],
        events=events,
    )
    extractor = StubAudioChunkExtractor(events)
    engine = StubTranscriptionEngine(
        results=[
            create_result(
                segments=(),
                model_name="model-a",
            ),
            create_result(
                segments=(),
                model_name="model-b",
            ),
        ],
        events=events,
    )

    pipeline = LongAudioTranscriptionPipeline(
        probe=probe,
        extractor=extractor,
        engine=engine,
        planner=AudioChunkPlanner(),
        merger=ChunkTranscriptMerger(),
    )

    with pytest.raises(
        TranscriptionError,
        match="inconsistent model names",
    ):
        pipeline.transcribe(
            source_path=source_path,
            workspace=tmp_path / "workspace",
            options=TranscriptionOptions(),
        )

    assert all(path.exists() is False for path in extractor.destination_paths)
