from fastapi.testclient import TestClient

from speech_transcription_service.config import Environment, Settings
from speech_transcription_service.main import create_app


def create_test_client() -> TestClient:
    settings = Settings(
        environment=Environment.TEST,
        docs_enabled=False,
    )
    return TestClient(create_app(settings))


def test_liveness_probe_returns_service_information() -> None:
    client = create_test_client()

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Speech Transcription Service",
        "version": "0.1.0",
        "environment": "test",
    }


def test_readiness_probe_returns_service_information() -> None:
    client = create_test_client()

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["environment"] == "test"


def test_documentation_can_be_disabled() -> None:
    client = create_test_client()

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
