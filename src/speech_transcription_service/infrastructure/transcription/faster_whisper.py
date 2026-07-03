from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Protocol, cast

from speech_transcription_service.domain.errors import (
    TranscriptionDependencyUnavailableError,
    TranscriptionError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)


class WhisperWord(Protocol):
    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def word(self) -> str: ...

    @property
    def probability(self) -> float: ...


class WhisperSegment(Protocol):
    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def text(self) -> str: ...

    @property
    def words(self) -> Iterable[WhisperWord] | None: ...


class WhisperInfo(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def language_probability(self) -> float: ...

    @property
    def duration(self) -> float: ...


class WhisperRuntimeModel(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        vad_filter: bool = False,
        word_timestamps: bool = False,
    ) -> tuple[Iterable[WhisperSegment], WhisperInfo]: ...


class WhisperModelFactory(Protocol):
    def __call__(
        self,
        model_size_or_path: str,
        *,
        device: str,
        compute_type: str,
        cpu_threads: int,
        num_workers: int,
        download_root: str | None,
        local_files_only: bool,
    ) -> WhisperRuntimeModel: ...


def load_faster_whisper_model(
    model_size_or_path: str,
    *,
    device: str,
    compute_type: str,
    cpu_threads: int,
    num_workers: int,
    download_root: str | None,
    local_files_only: bool,
) -> WhisperRuntimeModel:
    module = import_module("faster_whisper")
    model_class_value = vars(module).get("WhisperModel")

    if model_class_value is None:
        raise ImportError("The faster_whisper package does not expose WhisperModel.")

    model_class = cast(
        WhisperModelFactory,
        model_class_value,
    )

    return model_class(
        model_size_or_path,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers,
        download_root=download_root,
        local_files_only=local_files_only,
    )


class FasterWhisperEngine:
    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: Path | None = None,
        local_files_only: bool = False,
        model_factory: WhisperModelFactory | None = None,
    ) -> None:
        if not model_name.strip():
            raise ValueError("Model name cannot be empty.")

        if not device.strip():
            raise ValueError("Transcription device cannot be empty.")

        if not compute_type.strip():
            raise ValueError("Compute type cannot be empty.")

        if cpu_threads < 0:
            raise ValueError("CPU thread count cannot be negative.")

        if num_workers < 1:
            raise ValueError("Worker count must be at least one.")

        self._model_name = model_name.strip()
        self._device = device.strip()
        self._compute_type = compute_type.strip()
        self._cpu_threads = cpu_threads
        self._num_workers = num_workers
        self._download_root = str(download_root) if download_root is not None else None
        self._local_files_only = local_files_only

        self._model_factory = model_factory or load_faster_whisper_model

        self._model: WhisperRuntimeModel | None = None
        self._model_lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionResult:
        if not audio_path.is_file():
            raise TranscriptionError("The normalized audio file does not exist.")

        model = self._get_model()
        started_at = perf_counter()

        language = options.language.strip() if options.language is not None else None

        try:
            raw_segments, info = model.transcribe(
                str(audio_path),
                language=language,
                task="transcribe",
                beam_size=options.beam_size,
                vad_filter=options.vad_filter,
                word_timestamps=options.word_timestamps,
            )

            segments = self._convert_segments(raw_segments)

            processing_seconds = max(
                perf_counter() - started_at,
                0.0,
            )

            detected_language = info.language.strip() or None

            return TranscriptionResult(
                text=" ".join(segment.text for segment in segments),
                language=detected_language,
                language_probability=float(info.language_probability),
                duration_seconds=float(info.duration),
                segments=segments,
                model_name=self._model_name,
                processing_seconds=processing_seconds,
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError() from exc

    def _get_model(self) -> WhisperRuntimeModel:
        loaded_model = self._model

        if loaded_model is not None:
            return loaded_model

        with self._model_lock:
            loaded_model = self._model

            if loaded_model is not None:
                return loaded_model

            try:
                loaded_model = self._model_factory(
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=self._num_workers,
                    download_root=self._download_root,
                    local_files_only=self._local_files_only,
                )
            except TranscriptionDependencyUnavailableError:
                raise
            except Exception as exc:
                raise TranscriptionDependencyUnavailableError(
                    "The configured transcription model could not be loaded."
                ) from exc

            self._model = loaded_model
            return loaded_model

    @classmethod
    def _convert_segments(
        cls,
        raw_segments: Iterable[WhisperSegment],
    ) -> tuple[TranscriptSegment, ...]:
        converted: list[TranscriptSegment] = []

        for raw_segment in raw_segments:
            text = raw_segment.text.strip()

            if not text:
                continue

            converted.append(
                TranscriptSegment(
                    index=len(converted),
                    start_seconds=float(raw_segment.start),
                    end_seconds=float(raw_segment.end),
                    text=text,
                    words=cls._convert_words(raw_segment.words),
                )
            )

        return tuple(converted)

    @staticmethod
    def _convert_words(
        raw_words: Iterable[WhisperWord] | None,
    ) -> tuple[TranscriptWord, ...]:
        if raw_words is None:
            return ()

        converted: list[TranscriptWord] = []

        for raw_word in raw_words:
            text = raw_word.word.strip()

            if not text:
                continue

            converted.append(
                TranscriptWord(
                    start_seconds=float(raw_word.start),
                    end_seconds=float(raw_word.end),
                    text=text,
                    probability=float(raw_word.probability),
                )
            )

        return tuple(converted)
