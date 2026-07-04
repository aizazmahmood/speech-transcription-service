from speech_transcription_service.domain.exporters import (
    SrtTranscriptExporter,
    WebVttTranscriptExporter,
    export_srt,
    export_webvtt,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionResult,
    TranscriptSegment,
)


def create_transcription_result(
    segments: tuple[TranscriptSegment, ...],
) -> TranscriptionResult:
    return TranscriptionResult(
        text=" ".join(segment.text for segment in segments),
        language="en",
        language_probability=0.98,
        duration_seconds=10.0,
        segments=segments,
        model_name="stub-model",
        processing_seconds=0.5,
    )


def test_srt_exporter_formats_numbered_cues() -> None:
    transcript = create_transcription_result(
        segments=(
            TranscriptSegment(
                index=0,
                start_seconds=1.234,
                end_seconds=3.568,
                text="Hello world.",
            ),
            TranscriptSegment(
                index=1,
                start_seconds=3661.0,
                end_seconds=3662.25,
                text="Second segment.",
            ),
        )
    )

    assert SrtTranscriptExporter().export(transcript) == (
        "1\n"
        "00:00:01,234 --> 00:00:03,568\n"
        "Hello world.\n"
        "\n"
        "2\n"
        "01:01:01,000 --> 01:01:02,250\n"
        "Second segment.\n"
    )


def test_webvtt_exporter_formats_webvtt_document() -> None:
    transcript = create_transcription_result(
        segments=(
            TranscriptSegment(
                index=0,
                start_seconds=0.0,
                end_seconds=1.5,
                text="Opening line.",
            ),
            TranscriptSegment(
                index=1,
                start_seconds=2.0,
                end_seconds=4.25,
                text="Closing line.",
            ),
        )
    )

    assert WebVttTranscriptExporter().export(transcript) == (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:01.500\n"
        "Opening line.\n"
        "\n"
        "00:00:02.000 --> 00:00:04.250\n"
        "Closing line.\n"
    )


def test_export_helpers_return_expected_formats() -> None:
    transcript = create_transcription_result(
        segments=(
            TranscriptSegment(
                index=0,
                start_seconds=0.0,
                end_seconds=1.0,
                text="Hello world.",
            ),
        )
    )

    assert export_srt(transcript) == ("1\n00:00:00,000 --> 00:00:01,000\nHello world.\n")
    assert export_webvtt(transcript) == ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world.\n")


def test_exporters_handle_empty_transcript() -> None:
    transcript = create_transcription_result(
        segments=(),
    )

    assert export_srt(transcript) == ""
    assert export_webvtt(transcript) == "WEBVTT\n"


def test_exporters_normalize_multiline_and_unsafe_cue_text() -> None:
    transcript = create_transcription_result(
        segments=(
            TranscriptSegment(
                index=0,
                start_seconds=0.0,
                end_seconds=2.0,
                text="  First line  \r\nSecond --> line\x00  ",
            ),
        )
    )

    assert export_srt(transcript) == (
        "1\n00:00:00,000 --> 00:00:02,000\nFirst line\nSecond -> line\n"
    )
    assert export_webvtt(transcript) == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nFirst line\nSecond -> line\n"
    )
