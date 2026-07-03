from fastapi import Request
from fastapi.responses import JSONResponse

from speech_transcription_service.domain.errors import ServiceError


async def service_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, ServiceError):
        raise exc

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )
