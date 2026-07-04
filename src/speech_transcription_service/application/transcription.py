from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TranscriptionAudioContract:
    container_format: str = "wav"
    codec_name: str = "pcm_s16le"
    sample_rate_hz: int = 16_000
    channels: int = 1

    def __post_init__(self) -> None:
        if not self.container_format.strip():
            raise ValueError("Expected container format cannot be empty.")

        if not self.codec_name.strip():
            raise ValueError("Expected codec name cannot be empty.")

        if self.sample_rate_hz <= 0:
            raise ValueError("Expected sample rate must be greater than zero.")

        if self.channels <= 0:
            raise ValueError("Expected channel count must be greater than zero.")

    def validate(
        self,
        audio: ProbedAudio,
    ) -> None:
        violations: list[str] = []

        if audio.container_format != self.container_format:
            violations.append(
                f"container '{audio.container_format}' instead of '{self.container_format}'"
            )

        if audio.codec_name != self.codec_name:
            violations.append(f"codec '{audio.codec_name}' instead of '{self.codec_name}'")

        if audio.sample_rate_hz != self.sample_rate_hz:
            violations.append(
                f"sample rate {audio.sample_rate_hz} Hz instead of {self.sample_rate_hz} Hz"
            )

        if audio.channels != self.channels:
            violations.append(f"{audio.channels} channels instead of {self.channels}")

        if violations:
            details = "; ".join(violations)

            raise NormalizedAudioContractError(f"Normalized audio failed verification: {details}.")


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
        self._probe = probe
        self._normalizer = normalizer
        self._engine = engine
        self._audio_contract = TranscriptionAudioContract(
            codec_name=expected_codec_name,
            sample_rate_hz=expected_sample_rate_hz,
            channels=expected_channels,
        )

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> TranscriptionPipelineResult:
        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        resolved_source_audio = (
            source_audio if source_audio is not None else self._probe.inspect(source_path)
        )

        normalized_path = self._normalizer.normalize(
            source_path=source_path,
            destination_path=workspace / "normalized.wav",
        )

        normalized_audio = self._probe.inspect(normalized_path)
        self._audio_contract.validate(normalized_audio)

        transcript = self._engine.transcribe(
            audio_path=normalized_path,
            options=options,
        )

        return TranscriptionPipelineResult(
            source_audio=resolved_source_audio,
            normalized_audio=normalized_audio,
            transcript=transcript,
        )
