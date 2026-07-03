from pydantic import BaseModel, ConfigDict, Field


class AttributeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ProbedAudioResponse(AttributeResponse):
    container_format: str
    duration_seconds: float = Field(gt=0)
    codec_name: str
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    channel_layout: str | None
    bit_rate_bps: int | None


class AudioInspectionResponse(ProbedAudioResponse):
    filename: str
    content_type: str | None
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)


class UploadMetadataResponse(BaseModel):
    filename: str
    content_type: str | None
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)


class TranscriptWordResponse(AttributeResponse):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    probability: float | None = Field(default=None, ge=0, le=1)


class TranscriptSegmentResponse(AttributeResponse):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    words: tuple[TranscriptWordResponse, ...] = ()


class TranscriptResponse(AttributeResponse):
    text: str
    language: str | None
    language_probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    duration_seconds: float = Field(ge=0)
    segments: tuple[TranscriptSegmentResponse, ...]
    model_name: str
    processing_seconds: float = Field(ge=0)


class TranscriptionResponse(BaseModel):
    upload: UploadMetadataResponse
    source_audio: ProbedAudioResponse
    normalized_audio: ProbedAudioResponse
    transcript: TranscriptResponse
    real_time_factor: float | None = Field(default=None, ge=0)
