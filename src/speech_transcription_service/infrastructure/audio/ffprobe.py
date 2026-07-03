from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from speech_transcription_service.domain.audio import ProbedAudio
from speech_transcription_service.domain.errors import (
    InvalidAudioError,
    MediaDependencyUnavailableError,
    MediaInspectionError,
    MediaInspectionTimeoutError,
)


class FFprobeAudioProbe:
    def __init__(
        self,
        executable: str = "ffprobe",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def inspect(self, path: Path) -> ProbedAudio:
        if shutil.which(self._executable) is None:
            raise MediaDependencyUnavailableError(
                f"The configured FFprobe executable '{self._executable}' was not found."
            )

        command = [
            self._executable,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaInspectionTimeoutError() from exc
        except OSError as exc:
            raise MediaInspectionError() from exc

        if completed.returncode != 0:
            raise InvalidAudioError(
                "The uploaded file could not be decoded or does not contain valid media."
            )

        payload = self._decode_payload(completed.stdout)
        audio_stream = self._find_audio_stream(payload)

        format_value = payload.get("format")
        format_info = cast(dict[str, Any], format_value) if isinstance(format_value, dict) else {}

        duration = self._required_float(
            format_info.get("duration") or audio_stream.get("duration"),
            field_name="duration",
        )
        sample_rate = self._required_int(
            audio_stream.get("sample_rate"),
            field_name="sample rate",
        )
        channels = self._required_int(
            audio_stream.get("channels"),
            field_name="channel count",
        )

        if duration <= 0:
            raise InvalidAudioError("The audio stream has an invalid duration.")

        if sample_rate <= 0:
            raise InvalidAudioError("The audio stream has an invalid sample rate.")

        if channels <= 0:
            raise InvalidAudioError("The audio stream has an invalid channel count.")

        return ProbedAudio(
            container_format=self._required_string(
                format_info.get("format_name"),
                field_name="container format",
            ),
            duration_seconds=duration,
            codec_name=self._required_string(
                audio_stream.get("codec_name"),
                field_name="audio codec",
            ),
            sample_rate_hz=sample_rate,
            channels=channels,
            channel_layout=self._optional_string(audio_stream.get("channel_layout")),
            bit_rate_bps=self._optional_int(
                audio_stream.get("bit_rate") or format_info.get("bit_rate")
            ),
        )

    @staticmethod
    def _decode_payload(raw_output: str) -> dict[str, Any]:
        try:
            payload: object = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise MediaInspectionError("FFprobe returned malformed metadata.") from exc

        if not isinstance(payload, dict):
            raise MediaInspectionError("FFprobe returned an unexpected metadata structure.")

        return cast(dict[str, Any], payload)

    @staticmethod
    def _find_audio_stream(payload: dict[str, Any]) -> dict[str, Any]:
        streams_value = payload.get("streams")

        if not isinstance(streams_value, list):
            raise InvalidAudioError("The uploaded media does not contain an audio stream.")

        for stream in streams_value:
            if isinstance(stream, dict) and stream.get("codec_type") == "audio":
                return cast(dict[str, Any], stream)

        raise InvalidAudioError("The uploaded media does not contain an audio stream.")

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()

        raise InvalidAudioError(f"The audio metadata does not include a valid {field_name}.")

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    @staticmethod
    def _required_int(value: object, field_name: str) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError) as exc:
            raise InvalidAudioError(
                f"The audio metadata does not include a valid {field_name}."
            ) from exc

        return parsed

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None

        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _required_float(value: object, field_name: str) -> float:
        try:
            parsed = float(str(value))
        except (TypeError, ValueError) as exc:
            raise InvalidAudioError(
                f"The audio metadata does not include a valid {field_name}."
            ) from exc

        return parsed
