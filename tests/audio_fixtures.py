import io
import wave


def create_wave_bytes(
    duration_seconds: float = 0.25,
    sample_rate_hz: int = 16_000,
    channels: int = 1,
) -> bytes:
    if duration_seconds <= 0:
        raise ValueError("Duration must be greater than zero.")

    if sample_rate_hz <= 0:
        raise ValueError("Sample rate must be greater than zero.")

    if channels <= 0:
        raise ValueError("Channel count must be greater than zero.")

    frame_count = int(duration_seconds * sample_rate_hz)
    silent_frame = b"\x00\x00" * channels
    silent_frames = silent_frame * frame_count

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as audio_file:
        audio_file.setnchannels(channels)
        audio_file.setsampwidth(2)
        audio_file.setframerate(sample_rate_hz)
        audio_file.writeframes(silent_frames)

    return buffer.getvalue()
