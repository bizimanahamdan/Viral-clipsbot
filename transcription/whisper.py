"""
Whisper Transcription — Groq Whisper API integration.

Sends audio chunks to Groq's Whisper API for high-quality transcription
with word-level timestamps, confidence scores, and language detection.

Handles:
- Batch transcription of audio chunks
- Timestamp alignment across chunks
- Confidence scoring per word
- Language auto-detection
- SRT subtitle generation
- Full transcript assembly with deduplication
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ai.groq_client import groq_client
from configuration.config import GROQ_WHISPER_MODEL, TRANSCRIPTION_TIMEOUT
from utilities.logging_config import get_logger

logger = get_logger("transcription.whisper")


@dataclass
class WordTimestamp:
    """Represents a single word with timing and confidence information."""
    word: str
    start: float
    end: float
    confidence: float = 1.0
    language: str = ""

    @property
    def duration(self) -> float:
        """Return the duration of this word in seconds."""
        return self.end - self.start


@dataclass
class SentenceTimestamp:
    """Represents a sentence with timing information."""
    text: str
    start: float
    end: float
    words: list[WordTimestamp] = field(default_factory=list)


@dataclass
class Transcript:
    """Complete transcript with word and sentence timestamps."""
    text: str
    words: list[WordTimestamp] = field(default_factory=list)
    sentences: list[SentenceTimestamp] = field(default_factory=list)
    language: str = ""
    duration: float = 0.0
    chunks_processed: int = 0
    model_used: str = ""

    @property
    def word_count(self) -> int:
        return len(self.words)

    def get_text_between(self, start_time: float, end_time: float) -> str:
        """Get transcript text between two timestamps."""
        words_in_range = [
            w for w in self.words
            if start_time <= w.start < end_time
        ]
        return " ".join(w.word for w in words_in_range)

    def get_words_between(self, start_time: float, end_time: float) -> list[WordTimestamp]:
        """Get word timestamps between two timestamps."""
        return [
            w for w in self.words
            if start_time <= w.start < end_time
        ]


@dataclass
class TranscriptionResult:
    """Result of transcribing a video file."""
    transcript: Transcript
    chunk_results: list[dict] = field(default_factory=list)
    srt_content: str = ""


# ---------------------------------------------------------------------------
# SRT Utilities
# ---------------------------------------------------------------------------

def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT time code (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(
    transcript: Transcript,
    max_words_per_caption: int = 8,
    max_chars_per_line: int = 40,
) -> str:
    """
    Generate SRT subtitle file from transcript.

    Creates subtitle entries grouped by time intervals,
    respecting character and word limits per caption.

    Args:
        transcript: The complete transcript with timestamps.
        max_words_per_caption: Maximum words per caption entry.
        max_chars_per_line: Maximum characters per subtitle line.

    Returns:
        SRT-formatted string.
    """
    if not transcript.words:
        return ""

    srt_entries = []
    word_buffer = []
    entry_num = 1

    def flush_buffer():
        nonlocal entry_num
        if not word_buffer:
            return
        text = " ".join(w.word for w in word_buffer)
        start = word_buffer[0].start
        end = word_buffer[-1].end
        entry = (
            f"{entry_num}\n"
            f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
            f"{text}\n"
        )
        srt_entries.append(entry)
        entry_num += 1
        word_buffer.clear()

    for word in transcript.words:
        word_buffer.append(word)

        should_flush = (
            len(word_buffer) >= max_words_per_caption or
            len(" ".join(w.word for w in word_buffer)) >= max_chars_per_line or
            (word.word.endswith(('.', '!', '?')) and len(word_buffer) >= 3)
        )

        if should_flush:
            flush_buffer()

    flush_buffer()
    return "\n".join(srt_entries)


# ---------------------------------------------------------------------------
# Sentence Building
# ---------------------------------------------------------------------------

def _sentences_from_words(
    words: list[WordTimestamp],
    sentence_end_chars: set = {'.', '!', '?', '\n'},
) -> list[SentenceTimestamp]:
    """
    Build sentence timestamps from word timestamps.

    Groups words into sentences based on punctuation and capitalisation.
    """
    if not words:
        return []

    sentences = []
    current_words = []
    current_start = words[0].start

    for i, word in enumerate(words):
        current_words.append(word)

        # Check if this word ends a sentence
        if word.word and word.word[-1] in sentence_end_chars:
            sentences.append(SentenceTimestamp(
                text=" ".join(w.word for w in current_words),
                start=current_start,
                end=word.end,
                words=list(current_words),
            ))
            current_words = []
            next_idx = i + 1
            if next_idx < len(words):
                current_start = words[next_idx].start

    # Handle remaining words (no terminal punctuation)
    if current_words:
        sentences.append(SentenceTimestamp(
            text=" ".join(w.word for w in current_words),
            start=current_start,
            end=current_words[-1].end,
            words=current_words,
        ))

    return sentences


def _deduplicate_words(
    words: list[WordTimestamp],
    min_gap: float = 0.3,
) -> list[WordTimestamp]:
    """
    Remove duplicate words in overlap regions.

    When chunks overlap, the same words may appear twice.
    This function keeps the higher-confidence version.
    """
    if len(words) <= 1:
        return words

    deduped = [words[0]]

    for word in words[1:]:
        last = deduped[-1]
        time_diff = abs(word.start - last.end)
        is_duplicate = (
            time_diff < min_gap and
            word.word.lower() == last.word.lower()
        )

        if is_duplicate:
            if word.confidence > last.confidence:
                deduped[-1] = word
        else:
            deduped.append(word)

    return deduped


# ---------------------------------------------------------------------------
# Core Transcription
# ---------------------------------------------------------------------------

async def transcribe_chunk(
    audio_path: Path,
    language: Optional[str] = None,
    response_format: str = "verbose_json",
) -> dict:
    """
    Transcribe a single audio chunk using Groq Whisper API.

    Sends the audio file to Groq's Whisper API and returns the
    transcription with word-level timestamps and confidence scores.

    Args:
        audio_path: Path to the audio chunk file.
        language: Language code (e.g. 'en', 'es'). None for auto-detect.
        response_format: API response format ('verbose_json' for timestamps).

    Returns:
        Dict with 'text', 'words', 'language', 'segments' keys.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio chunk not found: {audio_path}")

    file_size = audio_path.stat().st_size
    logger.info(
        "Transcribing chunk: %s (%d bytes, %.1f KB)",
        audio_path.name, file_size, file_size / 1024,
    )

    result = await groq_client.transcribe(
        audio_file=audio_path,
        model=GROQ_WHISPER_MODEL,
        language=language,
        response_format=response_format,
        temperature=0.0,
    )

    logger.info(
        "Chunk transcribed: %d chars, lang=%s",
        len(result.get("text", "")),
        result.get("language", "unknown"),
    )

    return result


async def transcribe_chunks_parallel(
    audio_chunks: list[Path],
    language: Optional[str] = None,
    max_concurrent: int = 3,
    progress_callback=None,
) -> list[dict]:
    """
    Transcribe multiple audio chunks in parallel with rate limiting.

    Args:
        audio_chunks: List of paths to audio chunk files.
        language: Language code. None for auto-detect.
        max_concurrent: Maximum number of concurrent API calls.
        progress_callback: Optional callback(chunk_idx, chunk_result).

    Returns:
        List of transcription result dicts.
    """
    logger.info("Transcribing %d chunks with max %d concurrent", len(audio_chunks), max_concurrent)

    semaphore = asyncio.Semaphore(max_concurrent)
    results = [None] * len(audio_chunks)

    async def transcribe_one(idx: int, chunk_path: Path) -> dict:
        async with semaphore:
            try:
                result = await transcribe_chunk(chunk_path, language=language)
                results[idx] = result
                if progress_callback:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(idx, result)
                    else:
                        progress_callback(idx, result)
                return result
            except Exception as e:
                logger.error("Failed to transcribe chunk %d (%s): %s", idx, chunk_path.name, e)
                results[idx] = {"text": "", "words": [], "error": str(e)}
                return results[idx]

    tasks = [transcribe_one(i, path) for i, path in enumerate(audio_chunks)]
    await asyncio.gather(*tasks)

    return results


async def merge_chunk_transcripts(
    chunk_results: list[dict],
    chunk_paths: list[Path],
    chunk_duration: float = 600.0,
    overlap: float = 2.0,
) -> Transcript:
    """
    Merge multiple chunk transcripts into a single coherent transcript.

    Handles time offset calculation, duplicate removal in overlap
    regions, and confidence-based word selection.

    Args:
        chunk_results: List of transcription result dicts from Groq.
        chunk_paths: List of chunk file paths (for duration detection).
        chunk_duration: Duration of each chunk in seconds.
        overlap: Overlap between chunks in seconds.

    Returns:
        Merged Transcript with global timestamps.
    """
    all_words = []
    total_duration = 0.0
    detected_language = ""

    for idx, result in enumerate(chunk_results):
        # Calculate time offset for this chunk
        time_offset = idx * (chunk_duration - overlap)

        # Refine offset using actual chunk duration if available
        if chunk_paths and idx < len(chunk_paths) and chunk_paths[idx].exists():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(chunk_paths[idx]),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                actual_dur = float(stdout.decode().strip())
                if actual_dur > 0:
                    time_offset = idx * (actual_dur - overlap)
            except (ValueError, asyncio.TimeoutError, RuntimeError):
                pass

        # Process words with time offset
        words_data = result.get("words", [])
        for word_data in words_data:
            start = float(word_data.get("start", 0)) + time_offset
            end = float(word_data.get("end", 0)) + time_offset
            word_text = word_data.get("word", "").strip()
            confidence = float(word_data.get("probability", word_data.get("confidence", 1.0)))

            if word_text and start >= 0:
                all_words.append(WordTimestamp(
                    word=word_text,
                    start=round(start, 3),
                    end=round(end, 3),
                    confidence=round(confidence, 4),
                    language=result.get("language", ""),
                ))

        # Track language
        if not detected_language and result.get("language"):
            detected_language = result.get("language", "")

        # Track total duration
        if words_data:
            last_end = max(w.get("end", 0) for w in words_data) + time_offset
            total_duration = max(total_duration, last_end)

    # Remove duplicate words in overlap regions
    all_words = _deduplicate_words(all_words, min_gap=0.3)

    # Build full text and sentences
    full_text = " ".join(w.word for w in all_words)
    sentences = _sentences_from_words(all_words)

    transcript = Transcript(
        text=full_text,
        words=all_words,
        sentences=sentences,
        language=detected_language or "en",
        duration=total_duration,
        chunks_processed=len(chunk_results),
        model_used=GROQ_WHISPER_MODEL,
    )

    logger.info(
        "Merged transcript: %d words, %.1fs duration, lang=%s",
        len(all_words), total_duration, detected_language,
    )
    return transcript


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

async def transcribe_with_groq(
    audio_path: str | Path,
    language: Optional[str] = None,
) -> dict:
    """
    Transcribe audio using Groq's Whisper API (convenience function).

    Returns a dict with: text, segments, words, language.
    """
    logger.info("Transcribing with Groq Whisper: %s", Path(audio_path).name)
    result = await groq_client.transcribe(
        audio_file=Path(audio_path),
        language=language,
        response_format="verbose_json",
    )
    return result


async def transcribe_chunks(
    chunk_paths: list[Path],
    language: Optional[str] = None,
    on_progress=None,
) -> dict:
    """
    Transcribe multiple audio chunks and merge results.

    Args:
        chunk_paths: List of audio chunk file paths.
        language: Language code (None = auto-detect).
        on_progress: Optional async callback(progress, message).

    Returns:
        Merged transcription result dict.
    """
    chunk_results = await transcribe_chunks_parallel(
        chunk_paths,
        language=language,
        progress_callback=on_progress,
    )

    transcript = await merge_chunk_transcripts(
        chunk_results, chunk_paths,
    )

    merged = {
        "text": transcript.text,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in transcript.sentences
        ],
        "words": [
            {"word": w.word, "start": w.start, "end": w.end, "confidence": w.confidence}
            for w in transcript.words
        ],
        "language": transcript.language,
    }

    logger.info("Transcription complete: %d segments, %d words", len(transcript.sentences), len(transcript.words))
    return merged


async def save_transcription(
    transcript: Transcript,
    output_dir: Path,
    job_id: str,
) -> dict:
    """
    Save transcription results to files.

    Saves JSON, plain text, and SRT formats.

    Args:
        transcript: The transcript to save.
        output_dir: Directory to save files in.
        job_id: Job identifier for file naming.

    Returns:
        Dict with paths to saved files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save full transcript as JSON
    json_data = {
        "text": transcript.text,
        "language": transcript.language,
        "duration": transcript.duration,
        "model_used": transcript.model_used,
        "chunks_processed": transcript.chunks_processed,
        "words": [
            {"word": w.word, "start": w.start, "end": w.end, "confidence": w.confidence}
            for w in transcript.words
        ],
        "sentences": [
            {"text": s.text, "start": s.start, "end": s.end}
            for s in transcript.sentences
        ],
    }
    json_path = output_dir / f"{job_id}_transcript.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    # Save plain text transcript
    txt_path = output_dir / f"{job_id}_transcript.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(transcript.text)

    # Save SRT subtitles
    srt_path = output_dir / f"{job_id}_subtitles.srt"
    srt_content = generate_srt(transcript)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    logger.info("Transcription saved to %s", output_dir)

    return {
        "json": str(json_path),
        "txt": str(txt_path),
        "srt": str(srt_path),
    }


async def transcribe_full_video(
    video_path: Path,
    audio_chunks: list[Path],
    language: Optional[str] = None,
    max_concurrent: int = 3,
    progress_callback=None,
) -> TranscriptionResult:
    """
    Full transcription pipeline for a video.

    Orchestrates: chunk transcription -> merge -> SRT generation.

    Args:
        video_path: Path to the source video.
        audio_chunks: List of audio chunk paths to transcribe.
        language: Language code. None for auto-detect.
        max_concurrent: Max concurrent API calls.
        progress_callback: Optional progress callback.

    Returns:
        TranscriptionResult with full transcript and SRT.
    """
    logger.info("Starting full transcription for: %s (%d chunks)", video_path.name, len(audio_chunks))
    start_time = time.monotonic()

    # Step 1: Transcribe all chunks
    chunk_results = await transcribe_chunks_parallel(
        audio_chunks,
        language=language,
        max_concurrent=max_concurrent,
        progress_callback=progress_callback,
    )

    # Step 2: Merge results
    transcript = await merge_chunk_transcripts(
        chunk_results, audio_chunks,
    )

    # Step 3: Generate SRT
    srt_content = generate_srt(transcript)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Transcription complete: %d words, %.1fs duration, %.1fs elapsed",
        transcript.word_count, transcript.duration, elapsed,
    )

    return TranscriptionResult(
        transcript=transcript,
        chunk_results=chunk_results,
        srt_content=srt_content,
    )
