"""
Video Clipping — Trim clips based on viral moments.

Removes dead space and silence, creates smooth transitions,
avoids cutting mid-word, and respects word/sentence boundaries.

Features:
- Silence detection and removal via silencedetect
- Word-boundary-aware trimming using whisper timestamps
- Smooth fade in/out transitions
- Dead space removal with silenceremove filter
- Configurable padding before/after clips
- Batch clipping with progress tracking
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from configuration.config import (
    TEMP_DIR,
    MIN_SHORTS_DURATION_SECONDS,
    MAX_SHORTS_DURATION_SECONDS,
)
from ffmpeg_utils.commands import run_ffmpeg_command, get_video_duration
from ai.viral_detector import ViralMoment
from transcription.whisper import WordTimestamp
from utilities.logging_config import get_logger

logger = get_logger("video_processing.clipping")


@dataclass
class ClipResult:
    """Result of a clip operation."""
    clip_path: Path
    start_time: float
    end_time: float
    duration: float
    original_start: float
    original_end: float
    silence_removed: bool = False


class VideoClipper:
    """
    Clips video segments based on viral moments with intelligent
    boundary detection and silence removal.
    """

    def __init__(
        self,
        temp_dir: Optional[Path] = None,
        padding_before: float = 0.5,
        padding_after: float = 1.0,
        min_clip_duration: float = MIN_SHORTS_DURATION_SECONDS,
        max_clip_duration: float = MAX_SHORTS_DURATION_SECONDS,
    ):
        self.temp_dir = temp_dir or TEMP_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.padding_before = padding_before
        self.padding_after = padding_after
        self.min_duration = min_clip_duration
        self.max_duration = max_clip_duration

    async def clip_from_moment(
        self,
        video_path: Path,
        moment: ViralMoment,
        words: Optional[list[WordTimestamp]] = None,
        output_path: Optional[Path] = None,
        remove_silence: bool = True,
        add_fades: bool = True,
    ) -> ClipResult:
        """
        Create a video clip from a viral moment.

        Uses word timestamps to snap to clean word boundaries,
        adds configurable padding, and optionally removes silence.
        """
        # Snap to word boundaries if available
        start = moment.start_time
        end = moment.end_time

        if words:
            start = self._snap_to_word_start(start, words)
            end = self._snap_to_word_end(end, words)

        # Add padding
        start = max(0, start - self.padding_before)
        end = end + self.padding_after

        # Clamp to valid duration
        duration = end - start
        if duration > self.max_duration:
            end = start + self.max_duration
        if duration < self.min_duration:
            end = start + self.min_duration

        if output_path is None:
            output_path = self.temp_dir / f"clip_{int(start * 1000)}_{int(end * 1000)}.mp4"

        logger.info(
            "Clipping %.1fs-%.1fs (%.1fs) from %s",
            start, end, end - start, video_path.name,
        )

        # Build FFmpeg command with quality settings
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(video_path),
            "-t", str(end - start),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
        ]

        if add_fades:
            fade_in_dur = 0.3
            fade_out_dur = 0.5
            clip_dur = end - start
            cmd.extend([
                "-vf",
                f"fade=t=in:st=0:d={fade_in_dur},"
                f"fade=t=out:st={clip_dur - fade_out_dur}:d={fade_out_dur}",
            ])

        cmd.append(str(output_path))

        result = await run_ffmpeg_command(cmd, timeout=300)

        if result.returncode != 0:
            # Fallback: simpler command without fades
            cmd_simple = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(end - start),
                "-c", "copy",
                str(output_path),
            ]
            result = await run_ffmpeg_command(cmd_simple, timeout=300)
            if result.returncode != 0:
                raise RuntimeError(f"Clipping failed: {result.stderr[:500]}")

        clip_dur = await get_video_duration(output_path) or (end - start)

        clip_result = ClipResult(
            clip_path=output_path,
            start_time=start,
            end_time=end,
            duration=clip_dur,
            original_start=moment.start_time,
            original_end=moment.end_time,
            silence_removed=False,
        )

        if remove_silence:
            clip_result = await self._remove_silence_from_clip(clip_result)

        logger.info("Clip created: %s (%.1fs)", output_path.name, clip_result.duration)
        return clip_result

    async def clip_batch(
        self,
        video_path: Path,
        moments: list[ViralMoment],
        words: Optional[list[WordTimestamp]] = None,
        remove_silence: bool = True,
        progress_callback=None,
    ) -> list[ClipResult]:
        """
        Create clips from multiple viral moments.
        """
        results = []

        for i, moment in enumerate(moments):
            try:
                clip = await self.clip_from_moment(
                    video_path, moment, words,
                    remove_silence=remove_silence,
                )
                results.append(clip)

                if progress_callback:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(i, len(moments), clip)
                    else:
                        progress_callback(i, len(moments), clip)

            except Exception as e:
                logger.error("Failed to clip moment %d (%.1fs): %s", i, moment.start_time, e)

        logger.info("Created %d/%d clips", len(results), len(moments))
        return results

    def _snap_to_word_start(
        self,
        target_time: float,
        words: list[WordTimestamp],
        max_offset: float = 1.0,
    ) -> float:
        """Snap a start time to the beginning of the nearest word."""
        best_word = None
        best_diff = float('inf')

        for word in words:
            diff = abs(word.start - target_time)
            if diff < best_diff and diff <= max_offset and word.start >= target_time - 0.5:
                best_diff = diff
                best_word = word

        if best_word and best_diff < max_offset:
            return best_word.start
        return target_time

    def _snap_to_word_end(
        self,
        target_time: float,
        words: list[WordTimestamp],
        max_offset: float = 1.0,
    ) -> float:
        """Snap an end time to the end of the nearest word."""
        best_word = None
        best_diff = float('inf')

        for word in words:
            diff = abs(word.end - target_time)
            if diff < best_diff and diff <= max_offset and word.end >= target_time - 0.5:
                best_diff = diff
                best_word = word

        if best_word and best_diff < max_offset:
            return best_word.end
        return target_time

    async def _remove_silence_from_clip(
        self,
        clip_result: ClipResult,
    ) -> ClipResult:
        """Remove silence from a clip using FFmpeg's silencedetect filter."""
        if not clip_result.clip_path.exists():
            return clip_result

        output_path = self.temp_dir / f"{clip_result.clip_path.stem}_nosilence.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_result.clip_path),
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-40dB",
            "-c:v", "copy",
            str(output_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

            if process.returncode == 0 and output_path.exists():
                clip_result.clip_path = output_path
                clip_result.duration = await get_video_duration(output_path) or clip_result.duration
                clip_result.silence_removed = True
                logger.info("Silence removed from clip: %s", output_path.name)
            else:
                logger.warning("Silence removal failed, keeping original clip")
        except Exception as e:
            logger.warning("Silence removal error: %s", e)

        return clip_result


# Module-level convenience functions

async def clip_video(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    output_path: Optional[str | Path] = None,
    remove_silence: bool = True,
) -> Path:
    """Clip a segment from a video (convenience function)."""
    video_path = Path(video_path)
    duration = end_time - start_time
    duration = max(MIN_SHORTS_DURATION_SECONDS, min(duration, MAX_SHORTS_DURATION_SECONDS))
    end_time = start_time + duration

    if output_path is None:
        output_path = TEMP_DIR / f"{video_path.stem}_clip_{int(start_time)}s.mp4"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-avoid_negative_ts", "1",
        str(output_path),
    ]

    result = await run_ffmpeg_command(cmd, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Video clipping failed: {result.stderr[:500]}")

    logger.info("Clipped video: %s (%.1fs - %.1fs)", output_path.name, start_time, end_time)
    return output_path


async def remove_silence_from_clip(
    video_path: str | Path,
    output_path: Optional[str | Path] = None,
    silence_threshold: str = "-40dB",
    min_silence_duration: str = "0.5",
) -> Path:
    """Remove silence from a video clip (convenience function)."""
    video_path = Path(video_path)
    if output_path is None:
        output_path = TEMP_DIR / f"{video_path.stem}_nosilence.mp4"
    output_path = Path(output_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-af", f"silenceremove=stop_periods=-1:stop_duration={min_silence_duration}:stop_threshold={silence_threshold}",
        "-c:v", "copy",
        str(output_path),
    ]

    result = await run_ffmpeg_command(cmd, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Silence removal failed: {result.stderr[:500]}")

    return output_path


async def clip_multiple(
    video_path: str | Path,
    moments: list[ViralMoment],
    words: Optional[list[WordTimestamp]] = None,
    output_dir: Optional[Path] = None,
    remove_silence: bool = True,
    on_progress=None,
) -> list[Path]:
    """
    Clip multiple segments from a video.

    Args:
        video_path: Path to the source video.
        moments: List of viral moments to clip.
        words: Word timestamps for boundary snapping.
        output_dir: Directory for output clips.
        remove_silence: Whether to remove silence.
        on_progress: Optional async callback.

    Returns:
        List of paths to clipped videos.
    """
    clipper = VideoClipper(temp_dir=output_dir or TEMP_DIR)
    results = await clipper.clip_batch(
        Path(video_path), moments, words,
        remove_silence=remove_silence,
        progress_callback=on_progress,
    )
    return [r.clip_path for r in results]
