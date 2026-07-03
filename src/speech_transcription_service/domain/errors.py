from typing import ClassVar


class ServiceError(Exception):
    code: ClassVar[str] = "SERVICE_ERROR"
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "The service could not complete the request."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class UnsupportedMediaTypeError(ServiceError):
    code = "UNSUPPORTED_MEDIA_TYPE"
    status_code = 415
    default_message = "The uploaded media type is not supported."


class FileTooLargeError(ServiceError):
    code = "FILE_TOO_LARGE"
    status_code = 413
    default_message = "The uploaded file exceeds the configured size limit."


class EmptyFileError(ServiceError):
    code = "EMPTY_FILE"
    status_code = 400
    default_message = "The uploaded file is empty."


class InvalidAudioError(ServiceError):
    code = "INVALID_AUDIO"
    status_code = 422
    default_message = "The uploaded file could not be validated as audio."


class MediaDependencyUnavailableError(ServiceError):
    code = "MEDIA_DEPENDENCY_UNAVAILABLE"
    status_code = 503
    default_message = "A required media-processing dependency is unavailable."


class MediaInspectionTimeoutError(ServiceError):
    code = "MEDIA_INSPECTION_TIMEOUT"
    status_code = 504
    default_message = "Audio inspection exceeded the configured timeout."


class MediaInspectionError(ServiceError):
    code = "MEDIA_INSPECTION_FAILED"
    status_code = 500
    default_message = "Audio metadata could not be inspected."


class AudioNormalizationTimeoutError(ServiceError):
    code = "AUDIO_NORMALIZATION_TIMEOUT"
    status_code = 504
    default_message = "Audio normalization exceeded the configured timeout."


class AudioNormalizationError(ServiceError):
    code = "AUDIO_NORMALIZATION_FAILED"
    status_code = 500
    default_message = "The audio file could not be normalized."


class NormalizedAudioContractError(ServiceError):
    code = "NORMALIZED_AUDIO_CONTRACT_VIOLATION"
    status_code = 500
    default_message = "Normalized audio does not match the transcription input contract."


class TranscriptionDependencyUnavailableError(ServiceError):
    code = "TRANSCRIPTION_DEPENDENCY_UNAVAILABLE"
    status_code = 503
    default_message = "The transcription engine is unavailable."


class TranscriptionError(ServiceError):
    code = "TRANSCRIPTION_FAILED"
    status_code = 500
    default_message = "The audio could not be transcribed."
