from pathlib import Path

from speech_transcription_service.application.transcription import (
    TranscriptionAudioContract,
)
from speech_transcription_service.domain.audio import (
    AudioProbe,
    ProbedAudio,
)
from speech_transcription_service.domain.chunking import (
    AudioChunkExtractor,
    AudioChunkPlanner,
    ChunkedTranscriptionResult,
    ChunkTranscript,
    ChunkTranscriptMerger,
)
from speech_transcription_service.domain.errors import (
    TranscriptionError,
)
from speech_transcription_service.domain.transcription import (
    TranscriptionEngine,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
)


class LongAudioTranscriptionPipeline:
    def __init__(
        self,
        probe: AudioProbe,
        extractor: AudioChunkExtractor,
        engine: TranscriptionEngine,
        planner: AudioChunkPlanner,
        merger: ChunkTranscriptMerger,
        audio_contract: TranscriptionAudioContract | None = None,
    ) -> None:
        self._probe = probe
        self._extractor = extractor
        self._engine = engine
        self._planner = planner
        self._merger = merger
        self._audio_contract = (
            audio_contract if audio_contract is not None else TranscriptionAudioContract()
        )

    def transcribe(
        self,
        source_path: Path,
        workspace: Path,
        options: TranscriptionOptions,
        source_audio: ProbedAudio | None = None,
    ) -> ChunkedTranscriptionResult:
        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        resolved_source_audio = (
            source_audio if source_audio is not None else self._probe.inspect(source_path)
        )

        chunks = self._planner.plan(resolved_source_audio.duration_seconds)

        chunk_transcripts: list[ChunkTranscript] = []
        chunk_results: list[TranscriptionResult] = []
        effective_options = options

        for chunk in chunks:
            destination_path = workspace / "chunks" / f"chunk-{chunk.index:04d}.wav"

            extracted_path = self._extractor.extract(
                source_path=source_path,
                chunk=chunk,
                destination_path=destination_path,
            )

            try:
                chunk_audio = self._probe.inspect(extracted_path)
                self._audio_contract.validate(chunk_audio)

                chunk_result = self._engine.transcribe(
                    audio_path=extracted_path,
                    options=effective_options,
                )
            finally:
                extracted_path.unlink(missing_ok=True)

            chunk_results.append(chunk_result)
            chunk_transcripts.append(
                ChunkTranscript(
                    chunk=chunk,
                    segments=chunk_result.segments,
                )
            )

            effective_options = self._lock_detected_language(
                original_options=options,
                current_options=effective_options,
                chunk_result=chunk_result,
            )

        merged_segments = self._merger.merge(chunk_transcripts)

        transcript = self._assemble_transcript(
            source_duration_seconds=(resolved_source_audio.duration_seconds),
            segments=merged_segments,
            chunk_results=tuple(chunk_results),
            requested_language=options.language,
        )

        return ChunkedTranscriptionResult(
            source_audio=resolved_source_audio,
            chunks=chunks,
            transcript=transcript,
        )

    @staticmethod
    def _lock_detected_language(
        original_options: TranscriptionOptions,
        current_options: TranscriptionOptions,
        chunk_result: TranscriptionResult,
    ) -> TranscriptionOptions:
        if original_options.language is not None:
            return current_options

        if current_options.language is not None:
            return current_options

        if chunk_result.language is None:
            return current_options

        detected_language = chunk_result.language.strip()

        if not detected_language:
            return current_options

        return TranscriptionOptions(
            language=detected_language,
            beam_size=original_options.beam_size,
            vad_filter=original_options.vad_filter,
            word_timestamps=(original_options.word_timestamps),
        )

    @classmethod
    def _assemble_transcript(
        cls,
        source_duration_seconds: float,
        segments: tuple[TranscriptSegment, ...],
        chunk_results: tuple[TranscriptionResult, ...],
        requested_language: str | None,
    ) -> TranscriptionResult:
        if not chunk_results:
            raise TranscriptionError("Chunked transcription produced no chunk results.")

        model_names = {result.model_name for result in chunk_results}

        if len(model_names) != 1:
            raise TranscriptionError("Chunk transcription results used inconsistent model names.")

        language = cls._select_language(
            requested_language=requested_language,
            chunk_results=chunk_results,
        )

        language_probability = cls._average_language_probability(
            language=language,
            chunk_results=chunk_results,
        )

        return TranscriptionResult(
            text=" ".join(segment.text for segment in segments),
            language=language,
            language_probability=language_probability,
            duration_seconds=source_duration_seconds,
            segments=segments,
            model_name=chunk_results[0].model_name,
            processing_seconds=sum(result.processing_seconds for result in chunk_results),
        )

    @staticmethod
    def _select_language(
        requested_language: str | None,
        chunk_results: tuple[TranscriptionResult, ...],
    ) -> str | None:
        if requested_language is not None:
            return requested_language.strip()

        for result in chunk_results:
            if result.language is not None and result.language.strip():
                return result.language.strip()

        return None

    @staticmethod
    def _average_language_probability(
        language: str | None,
        chunk_results: tuple[TranscriptionResult, ...],
    ) -> float | None:
        if language is None:
            return None

        probabilities = [
            result.language_probability
            for result in chunk_results
            if (result.language == language and result.language_probability is not None)
        ]

        if not probabilities:
            return None

        return sum(probabilities) / len(probabilities)
