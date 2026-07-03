from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AudioInspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    content_type: str | None
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)

    container_format: str
    duration_seconds: float = Field(gt=0)
    codec_name: str
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    channel_layout: str | None
    bit_rate_bps: int | None
