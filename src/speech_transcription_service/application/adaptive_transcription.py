from pathlib import Path
from typing import Protocol

from speech_transcription_service.domain.audio import (
    AudioProbe,
    ProbedAudio,
)
from speech_transcription_service.domain.chunking import (
    ChunkedTranscriptionResult,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionExecutionResult,
    TranscriptionMode,
    TranscriptionOptions,
    TranscriptionPipelineResult,
)


class DirectTranscriptionPipeline(Protocol):
    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> TranscriptionPipelineResult:
        """Run direct transcription for one audio file."""
        ...


class ChunkedTranscriptionPipeline(Protocol):
    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> ChunkedTranscriptionResult:
        """Run chunked transcription for one audio file."""
        ...


class AdaptiveTranscriptionPipeline:
    def __init__(
        self,
        probe: AudioProbe,
        direct_pipeline: DirectTranscriptionPipeline,
        chunked_pipeline: ChunkedTranscriptionPipeline,
        chunking_threshold_seconds: float,
    ) -> None:
        if chunking_threshold_seconds <= 0:
            raise ValueError("Chunking threshold must be greater than zero.")

        self._probe = probe
        self._direct_pipeline = direct_pipeline
        self._chunked_pipeline = chunked_pipeline
        self._chunking_threshold_seconds = chunking_threshold_seconds

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionExecutionResult:
        source_audio = self._probe.inspect(source_path)

        if source_audio.duration_seconds <= self._chunking_threshold_seconds:
            direct_result = self._direct_pipeline.transcribe(
                source_path=source_path,
                workspace=workspace / "direct",
                options=options,
                source_audio=source_audio,
            )

            return TranscriptionExecutionResult(
                source_audio=direct_result.source_audio,
                normalized_audio=direct_result.normalized_audio,
                transcript=direct_result.transcript,
                mode=TranscriptionMode.DIRECT,
                chunk_count=1,
            )

        chunked_result = self._chunked_pipeline.transcribe(
            source_path=source_path,
            workspace=workspace / "chunked",
            options=options,
            source_audio=source_audio,
        )

        return TranscriptionExecutionResult(
            source_audio=chunked_result.source_audio,
            normalized_audio=None,
            transcript=chunked_result.transcript,
            mode=TranscriptionMode.CHUNKED,
            chunk_count=len(chunked_result.chunks),
        )
