import hashlib
from pathlib import Path

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from speech_transcription_service.application.audio_ingestion import (
    StagedUpload,
)
from speech_transcription_service.config import Settings
from speech_transcription_service.domain.errors import (
    EmptyFileError,
    FileTooLargeError,
)


async def stage_upload(
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
