import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from speech_transcription_service.config import Environment, Settings
from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.errors import (
    InvalidAudioError,
    ServiceError,
)
from speech_transcription_service.main import create_app
from tests.audio_fixtures import create_wave_bytes


class StubAudioProbe:
    def __init__(
        self,
        result: ProbedAudio | None = None,
        error: ServiceError | None = None,
    ) -> None:
        self.result = result or ProbedAudio(
            container_format="wav",
            duration_seconds=0.25,
            codec_name="pcm_s16le",
            sample_rate_hz=16_000,
            channels=1,
            channel_layout=None,
            bit_rate_bps=256_000,
        )
        self.error = error
        self.inspected_paths: list[Path] = []
        self.path_existed_during_inspection = False

    def inspect(self, path: Path) -> ProbedAudio:
        self.inspected_paths.append(path)
        self.path_existed_during_inspection = path.exists()

        if self.error is not None:
            raise self.error

        return self.result


def create_client(
    probe: StubAudioProbe,
    max_upload_bytes: int = 1024 * 1024,
    upload_chunk_bytes: int = 16,
) -> TestClient:
    settings = Settings(
        environment=Environment.TEST,
        docs_enabled=False,
        max_upload_bytes=max_upload_bytes,
        upload_chunk_bytes=upload_chunk_bytes,
    )

    return TestClient(
        create_app(
            settings=settings,
            audio_probe=probe,
        )
    )


def test_audio_inspection_returns_upload_and_media_metadata() -> None:
    probe = StubAudioProbe()
    client = create_client(probe)
    audio_bytes = create_wave_bytes()

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "sample.wav",
                audio_bytes,
                "audio/wav",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "filename": "sample.wav",
        "content_type": "audio/wav",
        "size_bytes": len(audio_bytes),
        "sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "container_format": "wav",
        "duration_seconds": 0.25,
        "codec_name": "pcm_s16le",
        "sample_rate_hz": 16_000,
        "channels": 1,
        "channel_layout": None,
        "bit_rate_bps": 256_000,
    }

    assert probe.path_existed_during_inspection is True
    assert len(probe.inspected_paths) == 1
    assert probe.inspected_paths[0].exists() is False


def test_audio_inspection_rejects_an_unsupported_extension() -> None:
    probe = StubAudioProbe()
    client = create_client(probe)

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "notes.txt",
                b"not audio",
                "text/plain",
            )
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == ("UNSUPPORTED_MEDIA_TYPE")
    assert probe.inspected_paths == []


def test_audio_inspection_rejects_an_explicit_non_audio_type() -> None:
    probe = StubAudioProbe()
    client = create_client(probe)

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "document.wav",
                b"not audio",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == ("UNSUPPORTED_MEDIA_TYPE")
    assert probe.inspected_paths == []


def test_audio_inspection_rejects_an_empty_file() -> None:
    probe = StubAudioProbe()
    client = create_client(probe)

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "empty.wav",
                b"",
                "audio/wav",
            )
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "EMPTY_FILE",
            "message": "The uploaded file is empty.",
        }
    }
    assert probe.inspected_paths == []


def test_audio_inspection_stops_when_size_limit_is_exceeded() -> None:
    probe = StubAudioProbe()
    client = create_client(
        probe,
        max_upload_bytes=8,
        upload_chunk_bytes=4,
    )

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "large.wav",
                b"x" * 12,
                "audio/wav",
            )
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert probe.inspected_paths == []


def test_audio_inspection_maps_probe_failure_to_structured_error() -> None:
    probe = StubAudioProbe(error=InvalidAudioError("The uploaded bytes are not valid audio."))
    client = create_client(probe)

    response = client.post(
        "/api/v1/audio/inspect",
        files={
            "file": (
                "fake.wav",
                b"not actually audio",
                "audio/wav",
            )
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_AUDIO",
            "message": "The uploaded bytes are not valid audio.",
        }
    }
