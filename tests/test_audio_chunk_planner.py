import pytest

from speech_transcription_service.domain.chunking import (
    AudioChunkPlanner,
)


def test_short_audio_produces_one_chunk() -> None:
    planner = AudioChunkPlanner(
        chunk_duration_seconds=30.0,
        overlap_seconds=5.0,
    )

    chunks = planner.plan(18.0)

    assert len(chunks) == 1

    chunk = chunks[0]

    assert chunk.index == 0
    assert chunk.start_seconds == 0.0
    assert chunk.end_seconds == 18.0
    assert chunk.keep_start_seconds == 0.0
    assert chunk.keep_end_seconds == 18.0
    assert chunk.duration_seconds == 18.0


def test_long_audio_produces_overlapping_chunks() -> None:
    planner = AudioChunkPlanner(
        chunk_duration_seconds=30.0,
        overlap_seconds=5.0,
    )

    chunks = planner.plan(70.0)

    assert [
        (
            chunk.start_seconds,
            chunk.end_seconds,
        )
        for chunk in chunks
    ] == [
        (0.0, 30.0),
        (25.0, 55.0),
        (50.0, 70.0),
    ]


def test_overlap_is_split_into_non_overlapping_keep_windows() -> None:
    planner = AudioChunkPlanner(
        chunk_duration_seconds=30.0,
        overlap_seconds=5.0,
    )

    chunks = planner.plan(70.0)

    assert [
        (
            chunk.keep_start_seconds,
            chunk.keep_end_seconds,
        )
        for chunk in chunks
    ] == [
        (0.0, 27.5),
        (27.5, 52.5),
        (52.5, 70.0),
    ]

    assert chunks[0].keep_end_seconds == (chunks[1].keep_start_seconds)
    assert chunks[1].keep_end_seconds == (chunks[2].keep_start_seconds)


def test_exactly_two_chunks_do_not_create_an_extra_chunk() -> None:
    planner = AudioChunkPlanner(
        chunk_duration_seconds=30.0,
        overlap_seconds=5.0,
    )

    chunks = planner.plan(55.0)

    assert [
        (
            chunk.start_seconds,
            chunk.end_seconds,
        )
        for chunk in chunks
    ] == [
        (0.0, 30.0),
        (25.0, 55.0),
    ]

    assert chunks[0].keep_end_seconds == 27.5
    assert chunks[1].keep_start_seconds == 27.5


@pytest.mark.parametrize(
    (
        "chunk_duration_seconds",
        "overlap_seconds",
        "expected_message",
    ),
    [
        (
            0.0,
            5.0,
            "Chunk duration must be greater than zero",
        ),
        (
            30.0,
            -1.0,
            "Chunk overlap cannot be negative",
        ),
        (
            30.0,
            30.0,
            "Chunk overlap must be shorter",
        ),
        (
            30.0,
            31.0,
            "Chunk overlap must be shorter",
        ),
    ],
)
def test_planner_rejects_invalid_configuration(
    chunk_duration_seconds: float,
    overlap_seconds: float,
    expected_message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        AudioChunkPlanner(
            chunk_duration_seconds=chunk_duration_seconds,
            overlap_seconds=overlap_seconds,
        )


def test_planner_rejects_invalid_audio_duration() -> None:
    planner = AudioChunkPlanner()

    with pytest.raises(
        ValueError,
        match="Audio duration must be greater than zero",
    ):
        planner.plan(0.0)
