from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.transcription import (
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    index: int
    start_seconds: float
    end_seconds: float
    keep_start_seconds: float
    keep_end_seconds: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("Chunk index cannot be negative.")

        if self.start_seconds < 0:
            raise ValueError("Chunk start time cannot be negative.")

        if self.end_seconds <= self.start_seconds:
            raise ValueError("Chunk end time must be later than its start time.")

        if self.keep_start_seconds < self.start_seconds:
            raise ValueError("Chunk keep-start time cannot be earlier than its start time.")

        if self.keep_end_seconds > self.end_seconds:
            raise ValueError("Chunk keep-end time cannot be later than its end time.")

        if self.keep_end_seconds <= self.keep_start_seconds:
            raise ValueError("Chunk keep window must have a positive duration.")

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class AudioChunkExtractor(Protocol):
    def extract(
        self,
        source_path: Path,
        chunk: AudioChunk,
        destination_path: Path,
    ) -> Path:
        """Extract one planned audio window into a local file."""
        ...


class AudioChunkPlanner:
    def __init__(
        self,
        chunk_duration_seconds: float = 30.0,
        overlap_seconds: float = 5.0,
    ) -> None:
        if chunk_duration_seconds <= 0:
            raise ValueError("Chunk duration must be greater than zero.")

        if overlap_seconds < 0:
            raise ValueError("Chunk overlap cannot be negative.")

        if overlap_seconds >= chunk_duration_seconds:
            raise ValueError("Chunk overlap must be shorter than the chunk duration.")

        self._chunk_duration_seconds = chunk_duration_seconds
        self._overlap_seconds = overlap_seconds

    def plan(
        self,
        total_duration_seconds: float,
    ) -> tuple[AudioChunk, ...]:
        if total_duration_seconds <= 0:
            raise ValueError("Audio duration must be greater than zero.")

        raw_windows = self._create_raw_windows(total_duration_seconds)
        boundaries = self._create_ownership_boundaries(raw_windows)

        chunks: list[AudioChunk] = []

        for index, (start_seconds, end_seconds) in enumerate(raw_windows):
            keep_start_seconds = 0.0 if index == 0 else boundaries[index - 1]
            keep_end_seconds = (
                total_duration_seconds if index == len(raw_windows) - 1 else boundaries[index]
            )

            chunks.append(
                AudioChunk(
                    index=index,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    keep_start_seconds=keep_start_seconds,
                    keep_end_seconds=keep_end_seconds,
                )
            )

        return tuple(chunks)

    def _create_raw_windows(
        self,
        total_duration_seconds: float,
    ) -> tuple[tuple[float, float], ...]:
        windows: list[tuple[float, float]] = []
        step_seconds = self._chunk_duration_seconds - self._overlap_seconds
        start_seconds = 0.0

        while start_seconds < total_duration_seconds:
            end_seconds = min(
                start_seconds + self._chunk_duration_seconds,
                total_duration_seconds,
            )

            windows.append(
                (
                    start_seconds,
                    end_seconds,
                )
            )

            if end_seconds >= total_duration_seconds:
                break

            start_seconds += step_seconds

        return tuple(windows)

    @staticmethod
    def _create_ownership_boundaries(
        windows: tuple[tuple[float, float], ...],
    ) -> tuple[float, ...]:
        boundaries: list[float] = []

        for current_window, next_window in zip(
            windows,
            windows[1:],
            strict=False,
        ):
            current_end_seconds = current_window[1]
            next_start_seconds = next_window[0]

            boundary_seconds = (current_end_seconds + next_start_seconds) / 2

            boundaries.append(boundary_seconds)

        return tuple(boundaries)


@dataclass(frozen=True, slots=True)
class ChunkTranscript:
    chunk: AudioChunk
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True, slots=True)
class ChunkedTranscriptionResult:
    source_audio: ProbedAudio
    chunks: tuple[AudioChunk, ...]
    transcript: TranscriptionResult


class ChunkTranscriptMerger:
    def merge(
        self,
        chunk_transcripts: Sequence[ChunkTranscript],
    ) -> tuple[TranscriptSegment, ...]:
        if not chunk_transcripts:
            return ()

        ordered_transcripts = tuple(
            sorted(
                chunk_transcripts,
                key=lambda item: item.chunk.index,
            )
        )

        self._validate_chunk_indexes(ordered_transcripts)

        retained_segments: list[
            tuple[
                float,
                float,
                int,
                int,
                AudioChunk,
                TranscriptSegment,
            ]
        ] = []

        for chunk_transcript in ordered_transcripts:
            chunk = chunk_transcript.chunk

            for segment in chunk_transcript.segments:
                global_start_seconds = chunk.start_seconds + segment.start_seconds
                global_end_seconds = chunk.start_seconds + segment.end_seconds
                midpoint_seconds = (global_start_seconds + global_end_seconds) / 2

                if not self._chunk_owns_timestamp(
                    chunk,
                    midpoint_seconds,
                ):
                    continue

                retained_segments.append(
                    (
                        global_start_seconds,
                        global_end_seconds,
                        chunk.index,
                        segment.index,
                        chunk,
                        segment,
                    )
                )

        retained_segments.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
            )
        )

        return tuple(
            self._rebase_segment(
                chunk=chunk,
                segment=segment,
                final_index=final_index,
            )
            for final_index, (
                _,
                _,
                _,
                _,
                chunk,
                segment,
            ) in enumerate(retained_segments)
        )

    @staticmethod
    def _validate_chunk_indexes(
        chunk_transcripts: Sequence[ChunkTranscript],
    ) -> None:
        actual_indexes = tuple(item.chunk.index for item in chunk_transcripts)
        expected_indexes = tuple(range(len(chunk_transcripts)))

        if actual_indexes != expected_indexes:
            raise ValueError(
                "Chunk transcript indexes must be unique and contiguous starting at zero."
            )

    @staticmethod
    def _chunk_owns_timestamp(
        chunk: AudioChunk,
        timestamp_seconds: float,
    ) -> bool:
        return chunk.keep_start_seconds <= timestamp_seconds < chunk.keep_end_seconds

    @classmethod
    def _rebase_segment(
        cls,
        chunk: AudioChunk,
        segment: TranscriptSegment,
        final_index: int,
    ) -> TranscriptSegment:
        return TranscriptSegment(
            index=final_index,
            start_seconds=(chunk.start_seconds + segment.start_seconds),
            end_seconds=(chunk.start_seconds + segment.end_seconds),
            text=segment.text,
            words=tuple(
                cls._rebase_word(
                    chunk=chunk,
                    word=word,
                )
                for word in segment.words
            ),
        )

    @staticmethod
    def _rebase_word(
        chunk: AudioChunk,
        word: TranscriptWord,
    ) -> TranscriptWord:
        return TranscriptWord(
            start_seconds=(chunk.start_seconds + word.start_seconds),
            end_seconds=(chunk.start_seconds + word.end_seconds),
            text=word.text,
            probability=word.probability,
        )
