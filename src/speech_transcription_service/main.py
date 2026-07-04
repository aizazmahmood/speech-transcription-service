from fastapi import FastAPI

from speech_transcription_service.api.error_handlers import (
    service_error_handler,
)
from speech_transcription_service.api.routes import (
    audio,
    health,
    transcriptions,
)
from speech_transcription_service.application.adaptive_transcription import (
    AdaptiveTranscriptionPipeline,
)
from speech_transcription_service.application.long_audio_transcription import (
    LongAudioTranscriptionPipeline,
)
from speech_transcription_service.application.transcription import (
    TranscriptionAudioContract,
    TranscriptionPipeline,
)
from speech_transcription_service.config import (
    Settings,
    get_settings,
)
from speech_transcription_service.domain.audio import (
    AudioNormalizer,
    AudioProbe,
)
from speech_transcription_service.domain.chunking import (
    AudioChunkExtractor,
    AudioChunkPlanner,
    ChunkTranscriptMerger,
)
from speech_transcription_service.domain.errors import ServiceError
from speech_transcription_service.domain.transcription import (
    TranscriptionEngine,
)
from speech_transcription_service.infrastructure.audio.ffmpeg import (
    FFmpegAudioNormalizer,
)
from speech_transcription_service.infrastructure.audio.ffmpeg_chunking import (
    FFmpegAudioChunkExtractor,
)
from speech_transcription_service.infrastructure.audio.ffprobe import (
    FFprobeAudioProbe,
)
from speech_transcription_service.infrastructure.transcription.faster_whisper import (
    FasterWhisperEngine,
)


def create_app(
    settings: Settings | None = None,
    audio_probe: AudioProbe | None = None,
    audio_normalizer: AudioNormalizer | None = None,
    audio_chunk_extractor: AudioChunkExtractor | None = None,
    transcription_engine: TranscriptionEngine | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    docs_url = "/docs" if resolved_settings.docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.docs_enabled else None

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "A production-minded speech-to-text service for "
            "timestamped transcription and downstream processing."
        ),
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    resolved_probe = (
        audio_probe
        if audio_probe is not None
        else FFprobeAudioProbe(
            executable=resolved_settings.ffprobe_path,
            timeout_seconds=(resolved_settings.ffprobe_timeout_seconds),
        )
    )

    resolved_normalizer = (
        audio_normalizer
        if audio_normalizer is not None
        else FFmpegAudioNormalizer(
            executable=resolved_settings.ffmpeg_path,
            timeout_seconds=(resolved_settings.ffmpeg_timeout_seconds),
            sample_rate_hz=(resolved_settings.normalized_sample_rate_hz),
            channels=resolved_settings.normalized_channels,
        )
    )

    resolved_chunk_extractor = (
        audio_chunk_extractor
        if audio_chunk_extractor is not None
        else FFmpegAudioChunkExtractor(
            executable=resolved_settings.ffmpeg_path,
            timeout_seconds=(resolved_settings.ffmpeg_timeout_seconds),
            sample_rate_hz=(resolved_settings.normalized_sample_rate_hz),
            channels=resolved_settings.normalized_channels,
        )
    )

    resolved_engine = (
        transcription_engine
        if transcription_engine is not None
        else FasterWhisperEngine(
            model_name=(resolved_settings.transcription_model_name),
            device=resolved_settings.transcription_device,
            compute_type=(resolved_settings.transcription_compute_type),
            cpu_threads=(resolved_settings.transcription_cpu_threads),
            num_workers=(resolved_settings.transcription_num_workers),
            download_root=(resolved_settings.transcription_download_root),
            local_files_only=(resolved_settings.transcription_local_files_only),
        )
    )

    audio_contract = TranscriptionAudioContract(
        codec_name="pcm_s16le",
        sample_rate_hz=(resolved_settings.normalized_sample_rate_hz),
        channels=resolved_settings.normalized_channels,
    )

    direct_pipeline = TranscriptionPipeline(
        probe=resolved_probe,
        normalizer=resolved_normalizer,
        engine=resolved_engine,
        expected_codec_name=audio_contract.codec_name,
        expected_sample_rate_hz=(audio_contract.sample_rate_hz),
        expected_channels=audio_contract.channels,
    )

    chunked_pipeline = LongAudioTranscriptionPipeline(
        probe=resolved_probe,
        extractor=resolved_chunk_extractor,
        engine=resolved_engine,
        planner=AudioChunkPlanner(
            chunk_duration_seconds=(resolved_settings.transcription_chunk_duration_seconds),
            overlap_seconds=(resolved_settings.transcription_chunk_overlap_seconds),
        ),
        merger=ChunkTranscriptMerger(),
        audio_contract=audio_contract,
    )

    adaptive_pipeline = AdaptiveTranscriptionPipeline(
        probe=resolved_probe,
        direct_pipeline=direct_pipeline,
        chunked_pipeline=chunked_pipeline,
        chunking_threshold_seconds=(resolved_settings.transcription_chunking_threshold_seconds),
    )

    application.state.settings = resolved_settings
    application.state.audio_probe = resolved_probe
    application.state.transcription_pipeline = adaptive_pipeline

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
    application.include_router(
        transcriptions.router,
        prefix=resolved_settings.api_prefix,
    )

    return application


app = create_app()
