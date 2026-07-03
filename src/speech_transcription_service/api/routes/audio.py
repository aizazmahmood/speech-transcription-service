from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, cast

from fastapi import APIRouter, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from speech_transcription_service.api.schemas import (
    AudioInspectionResponse,
    ErrorResponse,
)
from speech_transcription_service.api.upload import stage_upload
from speech_transcription_service.application.audio_ingestion import (
    AudioIngestionService,
    validate_upload_metadata,
)
from speech_transcription_service.config import Settings
from speech_transcription_service.domain.audio import AudioProbe

router = APIRouter(prefix="/audio", tags=["Audio"])


@router.post(
    "/inspect",
    response_model=AudioInspectionResponse,
    summary="Validate and inspect an uploaded audio file",
    responses={
        400: {"model": ErrorResponse, "description": "Empty upload"},
        413: {"model": ErrorResponse, "description": "Upload is too large"},
        415: {"model": ErrorResponse, "description": "Unsupported media"},
        422: {"model": ErrorResponse, "description": "Invalid audio"},
        503: {
            "model": ErrorResponse,
            "description": "Media dependency unavailable",
        },
        504: {
            "model": ErrorResponse,
            "description": "Media inspection timed out",
        },
    },
)
async def inspect_audio(
    request: Request,
    file: Annotated[
        UploadFile,
        File(description="Audio file to validate and inspect"),
    ],
) -> AudioInspectionResponse:
    validate_upload_metadata(file.filename, file.content_type)

    settings = cast(Settings, request.app.state.settings)
    probe = cast(AudioProbe, request.app.state.audio_probe)

    try:
        with TemporaryDirectory(prefix="sts-upload-") as temp_directory:
            staged_upload = await stage_upload(
                file=file,
                temporary_directory=Path(temp_directory),
                settings=settings,
            )

            service = AudioIngestionService(probe)

            inspection = await run_in_threadpool(
                service.inspect,
                staged_upload,
            )

            return AudioInspectionResponse.model_validate(inspection)
    finally:
        await file.close()
