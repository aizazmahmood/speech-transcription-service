from fastapi import FastAPI

from speech_transcription_service.api.error_handlers import (
    service_error_handler,
)
from speech_transcription_service.api.routes import audio, health
from speech_transcription_service.config import Settings, get_settings
from speech_transcription_service.domain.audio import AudioProbe
from speech_transcription_service.domain.errors import ServiceError
from speech_transcription_service.infrastructure.audio.ffprobe import (
    FFprobeAudioProbe,
)


def create_app(
    settings: Settings | None = None,
    audio_probe: AudioProbe | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    docs_url = "/docs" if resolved_settings.docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.docs_enabled else None

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "A production-minded speech-to-text service for timestamped "
            "transcription and downstream processing."
        ),
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    application.state.settings = resolved_settings
    application.state.audio_probe = audio_probe or FFprobeAudioProbe(
        executable=resolved_settings.ffprobe_path,
        timeout_seconds=resolved_settings.ffprobe_timeout_seconds,
    )

    application.add_exception_handler(
        ServiceError,
        service_error_handler,
    )

    application.include_router(
        health.router,
        prefix=resolved_settings.api_prefix,
    )
    application.include_router(
        audio.router,
        prefix=resolved_settings.api_prefix,
    )

    return application


app = create_app()
