from pathlib import Path

from speech_transcription_service.domain.audio import (
    AudioNormalizer,
    AudioProbe,
    ProbedAudio,
)
from speech_transcription_service.domain.errors import (
    NormalizedAudioContractError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionEngine,
    TranscriptionOptions,
    TranscriptionPipelineResult,
)


class TranscriptionPipeline:
    def __init__(
        self,
        probe: AudioProbe,
        normalizer: AudioNormalizer,
        engine: TranscriptionEngine,
        expected_codec_name: str = "pcm_s16le",
        expected_sample_rate_hz: int = 16_000,
        expected_channels: int = 1,
    ) -> None:
        if expected_sample_rate_hz <= 0:
            raise ValueError("Expected sample rate must be greater than zero.")

        if expected_channels <= 0:
            raise ValueError("Expected channel count must be greater than zero.")

        if not expected_codec_name.strip():
            raise ValueError("Expected codec name cannot be empty.")

        self._probe = probe
        self._normalizer = normalizer
        self._engine = engine
        self._expected_codec_name = expected_codec_name
        self._expected_sample_rate_hz = expected_sample_rate_hz
        self._expected_channels = expected_channels

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
    ) -> TranscriptionPipelineResult:
        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        source_audio = self._probe.inspect(source_path)

        normalized_path = self._normalizer.normalize(
            source_path=source_path,
            destination_path=workspace / "normalized.wav",
        )

        normalized_audio = self._probe.inspect(normalized_path)
        self._validate_normalized_audio(normalized_audio)

        transcript = self._engine.transcribe(
            audio_path=normalized_path,
            options=options,
        )

        return TranscriptionPipelineResult(
            source_audio=source_audio,
            normalized_audio=normalized_audio,
            transcript=transcript,
        )

    def _validate_normalized_audio(
        self,
        audio: ProbedAudio,
    ) -> None:
        violations: list[str] = []

        if audio.container_format != "wav":
            violations.append(f"container '{audio.container_format}' instead of 'wav'")

        if audio.codec_name != self._expected_codec_name:
            violations.append(
                f"codec '{audio.codec_name}' instead of '{self._expected_codec_name}'"
            )

        if audio.sample_rate_hz != self._expected_sample_rate_hz:
            violations.append(
                f"sample rate {audio.sample_rate_hz} Hz instead of "
                f"{self._expected_sample_rate_hz} Hz"
            )

        if audio.channels != self._expected_channels:
            violations.append(f"{audio.channels} channels instead of {self._expected_channels}")

        if violations:
            details = "; ".join(violations)

            raise NormalizedAudioContractError(f"Normalized audio failed verification: {details}.")
