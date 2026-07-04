from typing import Protocol

from speech_transcription_service.domain.transcription import (
    TranscriptionResult,
    TranscriptSegment,
)


class TranscriptExporter(Protocol):
    def export(
        self,
        transcript: TranscriptionResult,
    ) -> str:
        """Export a transcript into a downstream text format."""
        ...


class SrtTranscriptExporter:
    def export(
        self,
        transcript: TranscriptionResult,
    ) -> str:
        cues = [
            _format_srt_cue(
                cue_number=cue_number,
                segment=segment,
            )
            for cue_number, segment in enumerate(
                transcript.segments,
                start=1,
            )
        ]

        if not cues:
            return ""

        return "\n\n".join(cues) + "\n"


class WebVttTranscriptExporter:
    def export(
        self,
        transcript: TranscriptionResult,
    ) -> str:
        cues = [_format_webvtt_cue(segment) for segment in transcript.segments]

        if not cues:
            return "WEBVTT\n"

        return "WEBVTT\n\n" + "\n\n".join(cues) + "\n"


def export_srt(
    transcript: TranscriptionResult,
) -> str:
    return SrtTranscriptExporter().export(transcript)


def export_webvtt(
    transcript: TranscriptionResult,
) -> str:
    return WebVttTranscriptExporter().export(transcript)


def _format_srt_cue(
    cue_number: int,
    segment: TranscriptSegment,
) -> str:
    return (
        f"{cue_number}\n"
        f"{_format_timestamp(segment.start_seconds, millisecond_separator=',')} --> "
        f"{_format_timestamp(segment.end_seconds, millisecond_separator=',')}\n"
        f"{_normalize_cue_text(segment.text)}"
    )


def _format_webvtt_cue(
    segment: TranscriptSegment,
) -> str:
    return (
        f"{_format_timestamp(segment.start_seconds, millisecond_separator='.')} --> "
        f"{_format_timestamp(segment.end_seconds, millisecond_separator='.')}\n"
        f"{_normalize_cue_text(segment.text)}"
    )


def _format_timestamp(
    seconds: float,
    millisecond_separator: str,
) -> str:
    total_milliseconds = int(round(seconds * 1000))

    milliseconds = total_milliseconds % 1000
    total_seconds = total_milliseconds // 1000

    display_seconds = total_seconds % 60
    total_minutes = total_seconds // 60

    display_minutes = total_minutes % 60
    hours = total_minutes // 60

    return (
        f"{hours:02d}:"
        f"{display_minutes:02d}:"
        f"{display_seconds:02d}"
        f"{millisecond_separator}"
        f"{milliseconds:03d}"
    )


def _normalize_cue_text(
    text: str,
) -> str:
    normalized_text = (
        text.replace("\ufeff", "")
        .replace("\x00", "")
        .replace("-->", "->")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    lines = [line.strip() for line in normalized_text.split("\n") if line.strip()]

    if not lines:
        return "[inaudible]"

    return "\n".join(lines)
