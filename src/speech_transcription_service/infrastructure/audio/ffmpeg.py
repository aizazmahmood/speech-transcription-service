from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from speech_transcription_service.domain.errors import (
    AudioNormalizationError,
    AudioNormalizationTimeoutError,
    MediaDependencyUnavailableError,
)


class FFmpegAudioNormalizer:
    def __init__(
        self,
        executable: str = "ffmpeg",
        timeout_seconds: float = 300.0,
        sample_rate_hz: int = 16_000,
        channels: int = 1,
    ) -> None:
        if sample_rate_hz <= 0:
            raise ValueError("Sample rate must be greater than zero.")

        if channels != 1:
            raise ValueError("The transcription input contract requires mono audio.")

        self._executable = executable
        self._timeout_seconds = timeout_seconds
        self._sample_rate_hz = sample_rate_hz
        self._channels = channels

    def normalize(
        self,
        source_path: Path,
        destination_path: Path,
    ) -> Path:
        if shutil.which(self._executable) is None:
            raise MediaDependencyUnavailableError(
                f"The configured FFmpeg executable '{self._executable}' was not found."
            )

        if not source_path.is_file():
            raise AudioNormalizationError("The source audio file does not exist.")

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            self._executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-vn",
            "-map_metadata",
            "-1",
            "-ac",
            str(self._channels),
            "-ar",
            str(self._sample_rate_hz),
            "-c:a",
            "pcm_s16le",
            str(destination_path),
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
            self._remove_partial_output(destination_path)
            raise AudioNormalizationTimeoutError() from exc
        except OSError as exc:
            self._remove_partial_output(destination_path)
            raise AudioNormalizationError() from exc

        if completed.returncode != 0:
            self._remove_partial_output(destination_path)
            raise AudioNormalizationError("FFmpeg could not convert the source audio.")

        if not destination_path.is_file() or destination_path.stat().st_size == 0:
            self._remove_partial_output(destination_path)
            raise AudioNormalizationError("FFmpeg completed without producing a valid output file.")

        return destination_path

    @staticmethod
    def _remove_partial_output(path: Path) -> None:
        path.unlink(missing_ok=True)
