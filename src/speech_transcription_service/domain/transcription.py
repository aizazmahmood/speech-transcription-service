from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from speech_transcription_service.domain.audio import ProbedAudio


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    language: str | None = None
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False

    def __post_init__(self) -> None:
        if self.language is not None and not self.language.strip():
            raise ValueError("Language must be omitted or contain a valid language code.")

        if self.beam_size < 1:
            raise ValueError("Beam size must be at least one.")


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None = None

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("Word start time cannot be negative.")

        if self.end_seconds < self.start_seconds:
            raise ValueError("Word end time cannot be earlier than its start time.")

        if not self.text.strip():
            raise ValueError("Word text cannot be empty.")

        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError("Word probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    index: int
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[TranscriptWord, ...] = ()

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("Segment index cannot be negative.")

        if self.start_seconds < 0:
            raise ValueError("Segment start time cannot be negative.")

        if self.end_seconds < self.start_seconds:
            raise ValueError("Segment end time cannot be earlier than its start time.")

        if not self.text.strip():
            raise ValueError("Segment text cannot be empty.")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str | None
    language_probability: float | None
    duration_seconds: float
    segments: tuple[TranscriptSegment, ...]
    model_name: str
    processing_seconds: float

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("Audio duration cannot be negative.")

        if self.processing_seconds < 0:
            raise ValueError("Processing time cannot be negative.")

        if not self.model_name.strip():
            raise ValueError("Model name cannot be empty.")

        if self.language_probability is not None and not 0 <= self.language_probability <= 1:
            raise ValueError("Language probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class TranscriptionPipelineResult:
    source_audio: ProbedAudio
    normalized_audio: ProbedAudio
    transcript: TranscriptionResult


class TranscriptionEngine(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionResult:
        """Transcribe normalized audio into timestamped segments."""
        ...
