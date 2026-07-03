from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from speech_transcription_service.config import (
    Environment,
    Settings,
)
from speech_transcription_service.domain.audio import ProbedAudio
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


class StubTranscriptionEngine:
    def __init__(
        self,
        result: TranscriptionResult | None = None,
        error: TranscriptionError | None = None,
    ) -> None:
        self._result = result or create_transcription_result()
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


def create_normalized_audio() -> ProbedAudio:
    return ProbedAudio(
        container_format="wav",
        duration_seconds=8.0,
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


def create_client(
    probe: StubAudioProbe,
    normalizer: StubAudioNormalizer,
    engine: StubTranscriptionEngine,
) -> TestClient:
    settings = Settings(
        environment=Environment.TEST,
        docs_enabled=False,
        max_upload_bytes=1024 * 1024,
        upload_chunk_bytes=16,
    )

    return TestClient(
        create_app(
            settings=settings,
            audio_probe=probe,
            audio_normalizer=normalizer,
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
    assert probe.paths_existed == [True, True]

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
