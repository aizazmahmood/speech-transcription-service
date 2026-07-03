from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, cast

from fastapi import APIRouter, File, Form, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from speech_transcription_service.api.schemas import (
    ErrorResponse,
    ProbedAudioResponse,
    TranscriptionResponse,
    TranscriptResponse,
    UploadMetadataResponse,
)
from speech_transcription_service.api.upload import stage_upload
from speech_transcription_service.application.audio_ingestion import (
    validate_upload_metadata,
)
from speech_transcription_service.application.transcription import (
    TranscriptionPipeline,
)
from speech_transcription_service.config import Settings
from speech_transcription_service.domain.transcription import (
    TranscriptionOptions,
)

router = APIRouter(prefix="/transcriptions", tags=["Transcriptions"])


@router.post(
    "",
    response_model=TranscriptionResponse,
    summary="Transcribe an uploaded audio file",
    responses={
        400: {"model": ErrorResponse, "description": "Empty upload"},
        413: {"model": ErrorResponse, "description": "Upload is too large"},
        415: {"model": ErrorResponse, "description": "Unsupported media"},
        422: {"model": ErrorResponse, "description": "Invalid audio"},
        500: {
            "model": ErrorResponse,
            "description": "Media processing or transcription failed",
        },
        503: {
            "model": ErrorResponse,
            "description": "Required dependency is unavailable",
        },
        504: {
            "model": ErrorResponse,
            "description": "Media processing timed out",
        },
    },
)
async def create_transcription(
    request: Request,
    file: Annotated[
        UploadFile,
        File(description="Audio file to transcribe"),
    ],
    language: Annotated[
        str | None,
        Form(description="Optional spoken-language code"),
    ] = None,
    beam_size: Annotated[
        int,
        Form(ge=1, le=20),
    ] = 5,
    vad_filter: Annotated[
        bool,
        Form(),
    ] = True,
    word_timestamps: Annotated[
        bool,
        Form(),
    ] = False,
) -> TranscriptionResponse:
    validate_upload_metadata(file.filename, file.content_type)

    settings = cast(Settings, request.app.state.settings)
    pipeline = cast(
        TranscriptionPipeline,
        request.app.state.transcription_pipeline,
    )

    options = TranscriptionOptions(
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
    )

    try:
        with TemporaryDirectory(prefix="sts-transcription-") as temp_directory:
            temporary_path = Path(temp_directory)

            staged_upload = await stage_upload(
                file=file,
                temporary_directory=temporary_path,
                settings=settings,
            )

            result = await run_in_threadpool(
                pipeline.transcribe,
                staged_upload.path,
                temporary_path / "pipeline",
                options,
            )

            transcript = result.transcript
            real_time_factor = (
                transcript.processing_seconds / transcript.duration_seconds
                if transcript.duration_seconds > 0
                else None
            )

            return TranscriptionResponse(
                upload=UploadMetadataResponse(
                    filename=staged_upload.filename,
                    content_type=staged_upload.content_type,
                    size_bytes=staged_upload.size_bytes,
                    sha256=staged_upload.sha256,
                ),
                source_audio=ProbedAudioResponse.model_validate(result.source_audio),
                normalized_audio=ProbedAudioResponse.model_validate(result.normalized_audio),
                transcript=TranscriptResponse.model_validate(transcript),
                real_time_factor=real_time_factor,
            )
    finally:
        await file.close()
