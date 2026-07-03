from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from speech_transcription_service.config import Environment, Settings

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: Environment


def build_health_response(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Check whether the API process is running",
)
def liveness_probe(request: Request) -> HealthResponse:
    return build_health_response(request)


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Check whether the service is ready to accept work",
)
def readiness_probe(request: Request) -> HealthResponse:
    return build_health_response(request)
