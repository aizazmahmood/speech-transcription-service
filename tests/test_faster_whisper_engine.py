from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from speech_transcription_service.domain.errors import (
    TranscriptionDependencyUnavailableError,
    TranscriptionError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionOptions,
)
from speech_transcription_service.infrastructure.transcription.faster_whisper import (
    FasterWhisperEngine,
    WhisperInfo,
    WhisperModelFactory,
    WhisperRuntimeModel,
    WhisperSegment,
    WhisperWord,
)


@dataclass(frozen=True)
class FakeWord:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class FakeSegment:
    start: float
    end: float
    text: str
    words: Iterable[WhisperWord] | None = None


@dataclass(frozen=True)
class FakeInfo:
    language: str
    language_probability: float
    duration: float


class TrackingSegments:
    def __init__(
        self,
        segments: Iterable[WhisperSegment],
    ) -> None:
        self._segments = tuple(segments)
        self.consumed = False

    def __iter__(self) -> Iterator[WhisperSegment]:
        self.consumed = True
        return iter(self._segments)


class FailingSegments:
    def __iter__(self) -> Iterator[WhisperSegment]:
        raise RuntimeError("Inference failed while iterating segments.")


class FakeWhisperModel:
    def __init__(
        self,
        segments: Iterable[WhisperSegment],
        info: WhisperInfo,
    ) -> None:
        self._segments = segments
        self._info = info
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        audio: str,
        *,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        vad_filter: bool = False,
        word_timestamps: bool = False,
    ) -> tuple[Iterable[WhisperSegment], WhisperInfo]:
        self.calls.append(
            {
                "audio": audio,
                "language": language,
                "task": task,
                "beam_size": beam_size,
                "vad_filter": vad_filter,
                "word_timestamps": word_timestamps,
            }
        )

        return self._segments, self._info


class RecordingModelFactory:
    def __init__(
        self,
        model: WhisperRuntimeModel,
    ) -> None:
        self._model = model
        self.calls: list[dict[str, object]] = []

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
    ) -> WhisperRuntimeModel:
        self.calls.append(
            {
                "model_size_or_path": model_size_or_path,
                "device": device,
                "compute_type": compute_type,
                "cpu_threads": cpu_threads,
                "num_workers": num_workers,
                "download_root": download_root,
                "local_files_only": local_files_only,
            }
        )

        return self._model


class FailingModelFactory:
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
    ) -> WhisperRuntimeModel:
        del (
            model_size_or_path,
            device,
            compute_type,
            cpu_threads,
            num_workers,
            download_root,
            local_files_only,
        )

        raise RuntimeError("Model initialization failed.")


def create_audio_file(tmp_path: Path) -> Path:
    audio_path = tmp_path / "normalized.wav"
    audio_path.write_bytes(b"normalized audio")
    return audio_path


def test_engine_lazy_loads_maps_results_and_reuses_model(
    tmp_path: Path,
) -> None:
    words: list[WhisperWord] = [
        FakeWord(
            start=0.0,
            end=0.4,
            word=" Hello",
            probability=0.97,
        ),
        FakeWord(
            start=0.4,
            end=0.9,
            word=" world.",
            probability=0.93,
        ),
    ]

    segments: list[WhisperSegment] = [
        FakeSegment(
            start=0.0,
            end=0.9,
            text=" Hello world. ",
            words=words,
        ),
        FakeSegment(
            start=0.9,
            end=1.2,
            text="   ",
        ),
        FakeSegment(
            start=1.2,
            end=2.3,
            text=" Second segment. ",
        ),
    ]

    tracking_segments = TrackingSegments(segments)

    model = FakeWhisperModel(
        segments=tracking_segments,
        info=FakeInfo(
            language="en",
            language_probability=0.98,
            duration=2.5,
        ),
    )
    factory = RecordingModelFactory(model)

    engine = FasterWhisperEngine(
        model_name="small",
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=2,
        download_root=tmp_path / "models",
        model_factory=factory,
    )

    audio_path = create_audio_file(tmp_path)

    assert engine.is_loaded is False

    options = TranscriptionOptions(
        language=" en ",
        beam_size=3,
        vad_filter=True,
        word_timestamps=True,
    )

    result = engine.transcribe(audio_path, options)

    assert engine.is_loaded is True
    assert tracking_segments.consumed is True

    assert result.text == "Hello world. Second segment."
    assert result.language == "en"
    assert result.language_probability == 0.98
    assert result.duration_seconds == 2.5
    assert result.model_name == "small"
    assert result.processing_seconds >= 0

    assert len(result.segments) == 2
    assert result.segments[0].index == 0
    assert result.segments[1].index == 1

    assert result.segments[0].words[0].text == "Hello"
    assert result.segments[0].words[1].text == "world."
    assert result.segments[0].words[0].probability == 0.97

    assert factory.calls == [
        {
            "model_size_or_path": "small",
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 4,
            "num_workers": 2,
            "download_root": str(tmp_path / "models"),
            "local_files_only": False,
        }
    ]

    assert model.calls[0] == {
        "audio": str(audio_path),
        "language": "en",
        "task": "transcribe",
        "beam_size": 3,
        "vad_filter": True,
        "word_timestamps": True,
    }

    engine.transcribe(
        audio_path,
        TranscriptionOptions(),
    )

    assert len(factory.calls) == 1
    assert len(model.calls) == 2


def test_engine_maps_model_load_failure(
    tmp_path: Path,
) -> None:
    audio_path = create_audio_file(tmp_path)

    engine = FasterWhisperEngine(
        model_factory=FailingModelFactory(),
    )

    with pytest.raises(
        TranscriptionDependencyUnavailableError,
        match="could not be loaded",
    ):
        engine.transcribe(
            audio_path,
            TranscriptionOptions(),
        )

    assert engine.is_loaded is False


def test_engine_maps_lazy_inference_failure(
    tmp_path: Path,
) -> None:
    audio_path = create_audio_file(tmp_path)

    model = FakeWhisperModel(
        segments=FailingSegments(),
        info=FakeInfo(
            language="en",
            language_probability=0.9,
            duration=1.0,
        ),
    )
    factory: WhisperModelFactory = RecordingModelFactory(model)

    engine = FasterWhisperEngine(
        model_factory=factory,
    )

    with pytest.raises(TranscriptionError):
        engine.transcribe(
            audio_path,
            TranscriptionOptions(),
        )


def test_engine_rejects_missing_audio_before_loading_model(
    tmp_path: Path,
) -> None:
    factory = FailingModelFactory()

    engine = FasterWhisperEngine(
        model_factory=factory,
    )

    with pytest.raises(
        TranscriptionError,
        match="does not exist",
    ):
        engine.transcribe(
            tmp_path / "missing.wav",
            TranscriptionOptions(),
        )

    assert engine.is_loaded is False
