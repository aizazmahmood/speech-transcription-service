from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speech_transcription_service.config import (
    Environment,
    Settings,
)
from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.chunking import AudioChunk
from speech_transcription_service.domain.errors import (
    TranscriptionError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)
from speech_transcription_service.main import create_app
from tests.audio_fixtures import create_wave_bytes


class StubAudioProbe:
    def __init__(
        self,
        results: list[ProbedAudio],
    ) -> None:
        self._results: Iterator[ProbedAudio] = iter(results)
        self.paths: list[Path] = []
        self.paths_existed: list[bool] = []

    def inspect(self, path: Path) -> ProbedAudio:
        self.paths.append(path)
        self.paths_existed.append(path.exists())
        return next(self._results)


class StubAudioNormalizer:
    def __init__(self) -> None:
        self.source_paths: list[Path] = []
        self.destination_paths: list[Path] = []
        self.source_existed = False

    def normalize(
        self,
        source_path: Path,
        destination_path: Path,
    ) -> Path:
        self.source_paths.append(source_path)
        self.destination_paths.append(destination_path)
        self.source_existed = source_path.exists()

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination_path.write_bytes(b"normalized audio")

        return destination_path


class StubAudioChunkExtractor:
    def __init__(self) -> None:
        self.source_paths: list[Path] = []
        self.chunks: list[AudioChunk] = []
        self.destination_paths: list[Path] = []
        self.source_existed: list[bool] = []

    def extract(
        self,
        source_path: Path,
        chunk: AudioChunk,
        destination_path: Path,
    ) -> Path:
        self.source_paths.append(source_path)
        self.chunks.append(chunk)
        self.destination_paths.append(destination_path)
        self.source_existed.append(source_path.exists())

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination_path.write_bytes(b"chunk audio")

        return destination_path


class StubTranscriptionEngine:
    def __init__(
        self,
        result: TranscriptionResult | None = None,
        results: list[TranscriptionResult] | None = None,
        error: TranscriptionError | None = None,
    ) -> None:
        if result is not None and results is not None:
            raise ValueError("Provide either one result or multiple results, not both.")

        if results is not None:
            resolved_results = results
        else:
            resolved_result = result if result is not None else create_transcription_result()
            resolved_results = [resolved_result]

        self._results: Iterator[TranscriptionResult] = iter(resolved_results)
        self._error = error
        self.audio_paths: list[Path] = []
        self.options: list[TranscriptionOptions] = []
        self.audio_existed = False

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionResult:
        self.audio_paths.append(audio_path)
        self.options.append(options)
        self.audio_existed = audio_path.exists()

        if self._error is not None:
            raise self._error

        return next(self._results)


def create_source_audio(
    duration_seconds: float = 8.0,
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


def create_normalized_audio(
    duration_seconds: float = 8.0,
) -> ProbedAudio:
    return ProbedAudio(
        container_format="wav",
        duration_seconds=duration_seconds,
        codec_name="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        channel_layout=None,
        bit_rate_bps=256_000,
    )


def create_transcription_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="Hello world.",
        language="en",
        language_probability=0.98,
        duration_seconds=8.0,
        segments=(
            TranscriptSegment(
                index=0,
                start_seconds=0.0,
                end_seconds=1.0,
                text="Hello world.",
                words=(
                    TranscriptWord(
                        start_seconds=0.0,
                        end_seconds=0.4,
                        text="Hello",
                        probability=0.97,
                    ),
                    TranscriptWord(
                        start_seconds=0.4,
                        end_seconds=1.0,
                        text="world.",
                        probability=0.95,
                    ),
                ),
            ),
        ),
        model_name="stub-model",
        processing_seconds=0.4,
    )


def create_chunk_result(
    segments: tuple[TranscriptSegment, ...],
    duration_seconds: float,
    processing_seconds: float,
    language_probability: float,
) -> TranscriptionResult:
    return TranscriptionResult(
        text=" ".join(segment.text for segment in segments),
        language="en",
        language_probability=language_probability,
        duration_seconds=duration_seconds,
        segments=segments,
        model_name="stub-model",
        processing_seconds=processing_seconds,
    )


def create_client(
    probe: StubAudioProbe,
    normalizer: StubAudioNormalizer,
    engine: StubTranscriptionEngine,
    chunk_extractor: StubAudioChunkExtractor | None = None,
    chunking_threshold_seconds: float = 600.0,
    chunk_duration_seconds: float = 300.0,
    chunk_overlap_seconds: float = 5.0,
) -> TestClient:
    settings = Settings(
        environment=Environment.TEST,
        docs_enabled=False,
        max_upload_bytes=1024 * 1024,
        upload_chunk_bytes=16,
        transcription_chunking_threshold_seconds=(chunking_threshold_seconds),
        transcription_chunk_duration_seconds=(chunk_duration_seconds),
        transcription_chunk_overlap_seconds=(chunk_overlap_seconds),
    )

    return TestClient(
        create_app(
            settings=settings,
            audio_probe=probe,
            audio_normalizer=normalizer,
            audio_chunk_extractor=chunk_extractor,
            transcription_engine=engine,
        )
    )


def test_transcription_endpoint_runs_complete_pipeline() -> None:
    probe = StubAudioProbe(
        [
            create_source_audio(),
            create_normalized_audio(),
        ]
    )
    normalizer = StubAudioNormalizer()
    engine = StubTranscriptionEngine()
    client = create_client(probe, normalizer, engine)

    audio_bytes = create_wave_bytes()

    response = client.post(
        "/api/v1/transcriptions",
        files={
            "file": (
                "meeting.mp3",
                audio_bytes,
                "audio/mpeg",
            )
        },
        data={
            "language": "en",
            "beam_size": "3",
            "vad_filter": "true",
            "word_timestamps": "true",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["mode"] == "direct"
    assert payload["chunk_count"] == 1

    assert payload["upload"]["filename"] == "meeting.mp3"
    assert payload["upload"]["size_bytes"] == len(audio_bytes)
    assert len(payload["upload"]["sha256"]) == 64

    assert payload["source_audio"]["codec_name"] == "mp3"
    assert payload["normalized_audio"]["codec_name"] == "pcm_s16le"
    assert payload["normalized_audio"]["sample_rate_hz"] == 16_000

    assert payload["transcript"]["text"] == "Hello world."
    assert payload["transcript"]["language"] == "en"
    assert payload["transcript"]["model_name"] == "stub-model"
    assert payload["transcript"]["segments"][0]["index"] == 0
    assert payload["transcript"]["segments"][0]["words"][0]["text"] == "Hello"
    assert payload["real_time_factor"] == 0.05

    assert normalizer.source_existed is True
    assert engine.audio_existed is True
    assert probe.paths_existed == [
        True,
        True,
    ]

    assert engine.options == [
        TranscriptionOptions(
            language="en",
            beam_size=3,
            vad_filter=True,
            word_timestamps=True,
        )
    ]

    assert len(normalizer.source_paths) == 1
    assert len(normalizer.destination_paths) == 1
    assert len(engine.audio_paths) == 1

    assert normalizer.source_paths[0].exists() is False
    assert normalizer.destination_paths[0].exists() is False
    assert engine.audio_paths[0].exists() is False


def test_transcription_endpoint_processes_long_audio_in_chunks() -> None:
    probe = StubAudioProbe(
        [
            create_source_audio(),
            create_normalized_audio(
                duration_seconds=4.0,
            ),
            create_normalized_audio(
                duration_seconds=4.0,
            ),
            create_normalized_audio(
                duration_seconds=2.0,
            ),
        ]
    )
    normalizer = StubAudioNormalizer()
    chunk_extractor = StubAudioChunkExtractor()

    engine = StubTranscriptionEngine(
        results=[
            create_chunk_result(
                segments=(
                    TranscriptSegment(
                        index=0,
                        start_seconds=0.5,
                        end_seconds=1.5,
                        text="Opening segment.",
                    ),
                    TranscriptSegment(
                        index=1,
                        start_seconds=3.0,
                        end_seconds=3.4,
                        text="Shared speech.",
                    ),
                ),
                duration_seconds=4.0,
                processing_seconds=0.2,
                language_probability=0.9,
            ),
            create_chunk_result(
                segments=(
                    TranscriptSegment(
                        index=0,
                        start_seconds=0.0,
                        end_seconds=0.4,
                        text="Shared speech.",
                    ),
                    TranscriptSegment(
                        index=1,
                        start_seconds=1.0,
                        end_seconds=2.0,
                        text="Middle segment.",
                    ),
                ),
                duration_seconds=4.0,
                processing_seconds=0.3,
                language_probability=0.8,
            ),
            create_chunk_result(
                segments=(
                    TranscriptSegment(
                        index=0,
                        start_seconds=0.5,
                        end_seconds=1.5,
                        text="Closing segment.",
                    ),
                ),
                duration_seconds=2.0,
                processing_seconds=0.3,
                language_probability=0.7,
            ),
        ]
    )

    client = create_client(
        probe=probe,
        normalizer=normalizer,
        engine=engine,
        chunk_extractor=chunk_extractor,
        chunking_threshold_seconds=5.0,
        chunk_duration_seconds=4.0,
        chunk_overlap_seconds=1.0,
    )

    audio_bytes = create_wave_bytes(
        duration_seconds=0.5,
    )

    response = client.post(
        "/api/v1/transcriptions",
        files={
            "file": (
                "long-meeting.wav",
                audio_bytes,
                "audio/wav",
            )
        },
        data={
            "beam_size": "5",
            "vad_filter": "true",
            "word_timestamps": "false",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["mode"] == "chunked"
    assert payload["chunk_count"] == 3
    assert payload["normalized_audio"] is None

    assert payload["source_audio"]["duration_seconds"] == 8.0

    assert payload["transcript"]["text"] == (
        "Opening segment. Shared speech. Middle segment. Closing segment."
    )
    assert payload["transcript"]["duration_seconds"] == 8.0
    assert payload["transcript"]["language"] == "en"
    assert payload["transcript"]["language_probability"] == pytest.approx(0.8)
    assert payload["transcript"]["processing_seconds"] == pytest.approx(0.8)
    assert payload["real_time_factor"] == pytest.approx(0.1)

    assert [
        (
            segment["index"],
            segment["start_seconds"],
            segment["end_seconds"],
            segment["text"],
        )
        for segment in payload["transcript"]["segments"]
    ] == [
        (
            0,
            0.5,
            1.5,
            "Opening segment.",
        ),
        (
            1,
            3.0,
            3.4,
            "Shared speech.",
        ),
        (
            2,
            4.0,
            5.0,
            "Middle segment.",
        ),
        (
            3,
            6.5,
            7.5,
            "Closing segment.",
        ),
    ]

    assert [
        (
            chunk.start_seconds,
            chunk.end_seconds,
            chunk.keep_start_seconds,
            chunk.keep_end_seconds,
        )
        for chunk in chunk_extractor.chunks
    ] == [
        (
            0.0,
            4.0,
            0.0,
            3.5,
        ),
        (
            3.0,
            7.0,
            3.5,
            6.5,
        ),
        (
            6.0,
            8.0,
            6.5,
            8.0,
        ),
    ]

    assert normalizer.source_paths == []
    assert normalizer.destination_paths == []

    assert len(chunk_extractor.source_paths) == 3
    assert chunk_extractor.source_existed == [
        True,
        True,
        True,
    ]

    assert len(engine.audio_paths) == 3
    assert engine.options == [
        TranscriptionOptions(
            language=None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        ),
        TranscriptionOptions(
            language="en",
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        ),
        TranscriptionOptions(
            language="en",
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        ),
    ]

    assert probe.paths_existed == [
        True,
        True,
        True,
        True,
    ]

    assert all(path.exists() is False for path in chunk_extractor.destination_paths)
    assert all(path.exists() is False for path in engine.audio_paths)


def test_transcription_endpoint_returns_structured_engine_error() -> None:
    probe = StubAudioProbe(
        [
            create_source_audio(),
            create_normalized_audio(),
        ]
    )
    normalizer = StubAudioNormalizer()
    engine = StubTranscriptionEngine(error=TranscriptionError("Model inference failed."))
    client = create_client(probe, normalizer, engine)

    response = client.post(
        "/api/v1/transcriptions",
        files={
            "file": (
                "meeting.wav",
                create_wave_bytes(),
                "audio/wav",
            )
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "TRANSCRIPTION_FAILED",
            "message": "Model inference failed.",
        }
    }

    assert engine.audio_paths[0].exists() is False


def test_transcription_endpoint_rejects_unsupported_media_early() -> None:
    probe = StubAudioProbe([])
    normalizer = StubAudioNormalizer()
    engine = StubTranscriptionEngine()
    client = create_client(probe, normalizer, engine)

    response = client.post(
        "/api/v1/transcriptions",
        files={
            "file": (
                "notes.txt",
                b"not audio",
                "text/plain",
            )
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    assert probe.paths == []
    assert normalizer.source_paths == []
    assert engine.audio_paths == []
