from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, cast

from fastapi import APIRouter, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from speech_transcription_service.api.schemas import (
    AudioInspectionResponse,
    ErrorResponse,
)
from speech_transcription_service.application.audio_ingestion import (
    AudioIngestionService,
    StagedUpload,
    validate_upload_metadata,
)
from speech_transcription_service.config import Settings
from speech_transcription_service.domain.audio import AudioProbe
from speech_transcription_service.domain.errors import (
    EmptyFileError,
    FileTooLargeError,
)

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
            staged_upload = await _stage_upload(
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


async def _stage_upload(
    file: UploadFile,
    temporary_directory: Path,
    settings: Settings,
) -> StagedUpload:
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    staged_path = temporary_directory / f"source{suffix}"

    checksum = hashlib.sha256()
    size_bytes = 0

    with staged_path.open("wb") as destination:
        while True:
            chunk = await file.read(settings.upload_chunk_bytes)

            if not chunk:
                break

            size_bytes += len(chunk)

            if size_bytes > settings.max_upload_bytes:
                raise FileTooLargeError(
                    "The uploaded file exceeds the configured "
                    f"{settings.max_upload_bytes}-byte limit."
                )

            checksum.update(chunk)

            await run_in_threadpool(
                destination.write,
                chunk,
            )

    if size_bytes == 0:
        raise EmptyFileError()

    return StagedUpload(
        path=staged_path,
        filename=filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        sha256=checksum.hexdigest(),
    )
