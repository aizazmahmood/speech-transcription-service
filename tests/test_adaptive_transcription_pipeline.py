from pathlib import Path

import pytest

from speech_transcription_service.application.adaptive_transcription import (
    AdaptiveTranscriptionPipeline,
)
from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.chunking import (
    AudioChunk,
    ChunkedTranscriptionResult,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionMode,
    TranscriptionOptions,
    TranscriptionPipelineResult,
    TranscriptionResult,
    TranscriptSegment,
)


class StubAudioProbe:
    def __init__(
        self,
        result: ProbedAudio,
    ) -> None:
        self._result = result
        self.paths: list[Path] = []

    def inspect(
        self,
        path: Path,
    ) -> ProbedAudio:
        self.paths.append(path)
        return self._result


class StubDirectPipeline:
    def __init__(
        self,
        result: TranscriptionPipelineResult,
    ) -> None:
        self._result = result
        self.calls: list[
            tuple[
                Path,
                Path,
                TranscriptionOptions,
                ProbedAudio | None,
            ]
        ] = []

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> TranscriptionPipelineResult:
        self.calls.append(
            (
                source_path,
                workspace,
                options,
                source_audio,
            )
        )

        return self._result


class StubChunkedPipeline:
    def __init__(
        self,
        result: ChunkedTranscriptionResult,
    ) -> None:
        self._result = result
        self.calls: list[
            tuple[
                Path,
                Path,
                TranscriptionOptions,
                ProbedAudio | None,
            ]
        ] = []

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> ChunkedTranscriptionResult:
        self.calls.append(
            (
                source_path,
                workspace,
                options,
                source_audio,
            )
        )

        return self._result


def create_audio(
    duration_seconds: float,
    container_format: str = "mp3",
    codec_name: str = "mp3",
    sample_rate_hz: int = 48_000,
    channels: int = 2,
) -> ProbedAudio:
    return ProbedAudio(
        container_format=container_format,
        duration_seconds=duration_seconds,
        codec_name=codec_name,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        channel_layout=("stereo" if channels == 2 else None),
        bit_rate_bps=192_000,
    )


def create_transcript(
    duration_seconds: float,
) -> TranscriptionResult:
    segment = TranscriptSegment(
        index=0,
        start_seconds=0.0,
        end_seconds=1.0,
        text="Test transcript.",
    )

    return TranscriptionResult(
        text=segment.text,
        language="en",
        language_probability=0.9,
        duration_seconds=duration_seconds,
        segments=(segment,),
        model_name="stub-model",
        processing_seconds=0.2,
    )


def test_selector_uses_direct_pipeline_at_threshold(
    tmp_path: Path,
) -> None:
    source_audio = create_audio(600.0)
    normalized_audio = create_audio(
        duration_seconds=600.0,
        container_format="wav",
        codec_name="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
    )

    direct_pipeline = StubDirectPipeline(
        TranscriptionPipelineResult(
            source_audio=source_audio,
            normalized_audio=normalized_audio,
            transcript=create_transcript(600.0),
        )
    )

    chunked_pipeline = StubChunkedPipeline(
        ChunkedTranscriptionResult(
            source_audio=source_audio,
            chunks=(),
            transcript=create_transcript(600.0),
        )
    )

    probe = StubAudioProbe(source_audio)
    options = TranscriptionOptions()

    pipeline = AdaptiveTranscriptionPipeline(
        probe=probe,
        direct_pipeline=direct_pipeline,
        chunked_pipeline=chunked_pipeline,
        chunking_threshold_seconds=600.0,
    )

    result = pipeline.transcribe(
        source_path=tmp_path / "source.mp3",
        workspace=tmp_path / "workspace",
        options=options,
    )

    assert result.mode is TranscriptionMode.DIRECT
    assert result.chunk_count == 1
    assert result.normalized_audio == normalized_audio

    assert len(probe.paths) == 1
    assert len(direct_pipeline.calls) == 1
    assert chunked_pipeline.calls == []

    assert direct_pipeline.calls[0][1] == (tmp_path / "workspace" / "direct")
    assert direct_pipeline.calls[0][3] == source_audio


def test_selector_uses_chunked_pipeline_above_threshold(
    tmp_path: Path,
) -> None:
    source_audio = create_audio(601.0)

    chunks = (
        AudioChunk(
            index=0,
            start_seconds=0.0,
            end_seconds=600.0,
            keep_start_seconds=0.0,
            keep_end_seconds=597.5,
        ),
        AudioChunk(
            index=1,
            start_seconds=595.0,
            end_seconds=601.0,
            keep_start_seconds=597.5,
            keep_end_seconds=601.0,
        ),
    )

    direct_pipeline = StubDirectPipeline(
        TranscriptionPipelineResult(
            source_audio=source_audio,
            normalized_audio=create_audio(
                duration_seconds=601.0,
                container_format="wav",
                codec_name="pcm_s16le",
                sample_rate_hz=16_000,
                channels=1,
            ),
            transcript=create_transcript(601.0),
        )
    )

    chunked_pipeline = StubChunkedPipeline(
        ChunkedTranscriptionResult(
            source_audio=source_audio,
            chunks=chunks,
            transcript=create_transcript(601.0),
        )
    )

    probe = StubAudioProbe(source_audio)

    options = TranscriptionOptions(
        language="en",
    )

    pipeline = AdaptiveTranscriptionPipeline(
        probe=probe,
        direct_pipeline=direct_pipeline,
        chunked_pipeline=chunked_pipeline,
        chunking_threshold_seconds=600.0,
    )

    result = pipeline.transcribe(
        source_path=tmp_path / "source.mp3",
        workspace=tmp_path / "workspace",
        options=options,
    )

    assert result.mode is TranscriptionMode.CHUNKED
    assert result.chunk_count == 2
    assert result.normalized_audio is None

    assert len(probe.paths) == 1
    assert direct_pipeline.calls == []
    assert len(chunked_pipeline.calls) == 1

    assert chunked_pipeline.calls[0][1] == (tmp_path / "workspace" / "chunked")
    assert chunked_pipeline.calls[0][3] == source_audio


@pytest.mark.parametrize(
    "threshold",
    [
        0.0,
        -1.0,
    ],
)
def test_selector_rejects_invalid_threshold(
    threshold: float,
) -> None:
    source_audio = create_audio(10.0)

    direct_pipeline = StubDirectPipeline(
        TranscriptionPipelineResult(
            source_audio=source_audio,
            normalized_audio=create_audio(
                duration_seconds=10.0,
                container_format="wav",
                codec_name="pcm_s16le",
                sample_rate_hz=16_000,
                channels=1,
            ),
            transcript=create_transcript(10.0),
        )
    )

    chunked_pipeline = StubChunkedPipeline(
        ChunkedTranscriptionResult(
            source_audio=source_audio,
            chunks=(),
            transcript=create_transcript(10.0),
        )
    )

    with pytest.raises(
        ValueError,
        match="Chunking threshold must be greater than zero",
    ):
        AdaptiveTranscriptionPipeline(
            probe=StubAudioProbe(source_audio),
            direct_pipeline=direct_pipeline,
            chunked_pipeline=chunked_pipeline,
            chunking_threshold_seconds=threshold,
        )
