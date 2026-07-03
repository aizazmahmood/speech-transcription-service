from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from speech_transcription_service import __version__


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    app_name: str = "Speech Transcription Service"
    app_version: str = __version__
    environment: Environment = Environment.LOCAL
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True

    max_upload_bytes: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
    )
    upload_chunk_bytes: int = Field(
        default=1024 * 1024,
        gt=0,
    )

    ffprobe_path: str = "ffprobe"
    ffprobe_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
    )

    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
    )

    normalized_sample_rate_hz: int = Field(
        default=16_000,
        gt=0,
    )

    normalized_channels: int = Field(
        default=1,
        ge=1,
        le=1,
    )

    transcription_model_name: str = "small"
    transcription_device: str = "cpu"
    transcription_compute_type: str = "int8"

    transcription_cpu_threads: int = Field(
        default=0,
        ge=0,
    )
    transcription_num_workers: int = Field(
        default=1,
        ge=1,
    )

    transcription_download_root: Path | None = None
    transcription_local_files_only: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="STS_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
