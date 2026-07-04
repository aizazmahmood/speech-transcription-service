import pytest

from speech_transcription_service.domain.chunking import (
    AudioChunk,
    AudioChunkPlanner,
    ChunkTranscript,
    ChunkTranscriptMerger,
)
from speech_transcription_service.domain.transcription import (
    TranscriptSegment,
    TranscriptWord,
)


def create_segment(
    index: int,
    start_seconds: float,
    end_seconds: float,
    text: str,
    words: tuple[TranscriptWord, ...] = (),
) -> TranscriptSegment:
    return TranscriptSegment(
        index=index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        words=words,
    )


def create_chunks() -> tuple[AudioChunk, ...]:
    planner = AudioChunkPlanner(
        chunk_duration_seconds=30.0,
        overlap_seconds=5.0,
    )

    return planner.plan(70.0)


def test_merger_rebases_and_orders_out_of_order_results() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    chunk_zero = ChunkTranscript(
        chunk=chunks[0],
        segments=(
            create_segment(
                index=4,
                start_seconds=2.0,
                end_seconds=4.0,
                text="First segment.",
            ),
        ),
    )
    chunk_one = ChunkTranscript(
        chunk=chunks[1],
        segments=(
            create_segment(
                index=8,
                start_seconds=5.0,
                end_seconds=7.0,
                text="Second segment.",
            ),
        ),
    )
    chunk_two = ChunkTranscript(
        chunk=chunks[2],
        segments=(),
    )

    merged = merger.merge(
        [
            chunk_two,
            chunk_one,
            chunk_zero,
        ]
    )

    assert [
        (
            segment.index,
            segment.start_seconds,
            segment.end_seconds,
            segment.text,
        )
        for segment in merged
    ] == [
        (
            0,
            2.0,
            4.0,
            "First segment.",
        ),
        (
            1,
            30.0,
            32.0,
            "Second segment.",
        ),
    ]


def test_merger_removes_duplicate_from_overlap() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    merged = merger.merge(
        [
            ChunkTranscript(
                chunk=chunks[0],
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=25.0,
                        end_seconds=27.0,
                        text="Shared speech.",
                    ),
                ),
            ),
            ChunkTranscript(
                chunk=chunks[1],
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=0.0,
                        end_seconds=2.0,
                        text="Shared speech.",
                    ),
                ),
            ),
            ChunkTranscript(
                chunk=chunks[2],
                segments=(),
            ),
        ]
    )

    assert len(merged) == 1
    assert merged[0].start_seconds == 25.0
    assert merged[0].end_seconds == 27.0
    assert merged[0].text == "Shared speech."


def test_segment_at_boundary_belongs_to_later_chunk() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    merged = merger.merge(
        [
            ChunkTranscript(
                chunk=chunks[0],
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=26.5,
                        end_seconds=28.5,
                        text="Earlier chunk version.",
                    ),
                ),
            ),
            ChunkTranscript(
                chunk=chunks[1],
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=1.5,
                        end_seconds=3.5,
                        text="Later chunk version.",
                    ),
                ),
            ),
            ChunkTranscript(
                chunk=chunks[2],
                segments=(),
            ),
        ]
    )

    assert len(merged) == 1
    assert merged[0].start_seconds == 26.5
    assert merged[0].end_seconds == 28.5
    assert merged[0].text == "Later chunk version."


def test_merger_rebases_word_timestamps() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    merged = merger.merge(
        [
            ChunkTranscript(
                chunk=chunks[0],
                segments=(),
            ),
            ChunkTranscript(
                chunk=chunks[1],
                segments=(
                    create_segment(
                        index=0,
                        start_seconds=5.0,
                        end_seconds=7.0,
                        text="Hello world.",
                        words=(
                            TranscriptWord(
                                start_seconds=5.0,
                                end_seconds=5.5,
                                text="Hello",
                                probability=0.98,
                            ),
                            TranscriptWord(
                                start_seconds=5.5,
                                end_seconds=7.0,
                                text="world.",
                                probability=0.96,
                            ),
                        ),
                    ),
                ),
            ),
            ChunkTranscript(
                chunk=chunks[2],
                segments=(),
            ),
        ]
    )

    assert len(merged) == 1

    segment = merged[0]

    assert segment.start_seconds == 30.0
    assert segment.end_seconds == 32.0

    assert [
        (
            word.start_seconds,
            word.end_seconds,
            word.text,
            word.probability,
        )
        for word in segment.words
    ] == [
        (
            30.0,
            30.5,
            "Hello",
            0.98,
        ),
        (
            30.5,
            32.0,
            "world.",
            0.96,
        ),
    ]


def test_merger_rejects_duplicate_chunk_indexes() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    duplicate = ChunkTranscript(
        chunk=chunks[0],
        segments=(),
    )

    with pytest.raises(
        ValueError,
        match="unique and contiguous",
    ):
        merger.merge(
            [
                duplicate,
                duplicate,
            ]
        )


def test_merger_rejects_missing_chunk_indexes() -> None:
    chunks = create_chunks()
    merger = ChunkTranscriptMerger()

    with pytest.raises(
        ValueError,
        match="unique and contiguous",
    ):
        merger.merge(
            [
                ChunkTranscript(
                    chunk=chunks[0],
                    segments=(),
                ),
                ChunkTranscript(
                    chunk=chunks[2],
                    segments=(),
                ),
            ]
        )


def test_empty_chunk_results_produce_empty_transcript() -> None:
    merger = ChunkTranscriptMerger()

    assert merger.merge([]) == ()
