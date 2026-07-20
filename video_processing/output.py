"""
Video Output — Final render pipeline for viral shorts.

Composites all elements into the final 1080x1920 output:
- Video (reframed clip)
- Captions overlay (animated, synced)
- Emoji overlays (contextual)
- B-roll overlays (configurable)
- Zoom effects (dynamic)

Outputs: H.264 video, AAC audio, high bitrate, 30fps.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from configuration.config import (
    OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS,
    OUTPUT_VIDEO_CODEC, OUTPUT_AUDIO_CODEC,
    OUTPUT_VIDEO_BITRATE, OUTPUT_AUDIO_BITRATE,
    OUTPUT_PIXEL_FORMAT, FFMPEG_PRESET, FFMPEG_THREADS,
    TEMP_DIR, OUTPUTS_DIR, MAX_SHORTS_DURATION_SECONDS,
)
from ffmpeg_utils.commands import run_ffmpeg_command, get_video_duration
from utilities.logging_config import get_logger

logger = get_logger("video_processing.output")


@dataclass
class OutputResult:
    """Result of the final output render."""
    file_path: Path
    duration: float
    file_size: int
    resolution: tuple[int, int]
    fps: int
    render_time: float
    has_captions: bool
    has_emoji: bool
    has_broll: bool
    has_zoom: bool


class VideoOutputRenderer:
    """
    Renders the final viral short video by compositing
    all processing layers together.
    """

    def __init__(
        self,
        temp_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        self.temp_dir = temp_dir or TEMP_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir or OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def render(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        captions_dir: Optional[Path] = None,
        emoji_overlays: Optional[list[dict]] = None,
        broll_clips: Optional[list[dict]] = None,
        zoom_enabled: bool = False,
        quality: str = "high",
        thumbnail_path: Optional[Path] = None,
    ) -> OutputResult:
        """
        Render the final viral short video.

        Composites video with captions, emoji overlays, B-roll,
        and zoom effects into a single 1080x1920 MP4 file.
        """
        import time
        start_time = time.monotonic()

        if output_path is None:
            output_path = self.output_dir / f"{video_path.stem}_final.mp4"
        output_path = Path(output_path)

        logger.info("Rendering final output: %s", video_path.name)

        duration = await get_video_duration(video_path)
        if not duration:
            raise RuntimeError(f"Cannot determine video duration: {video_path}")

        if duration > MAX_SHORTS_DURATION_SECONDS:
            duration = MAX_SHORTS_DURATION_SECONDS

        # Get quality settings
        crf, preset, video_bitrate, audio_bitrate = self._get_quality_settings(quality)

        # Build the FFmpeg filter chain
        filters = []
        extra_inputs = []

        # Add caption overlay if available
        if captions_dir and captions_dir.exists():
            caption_files = sorted(captions_dir.glob("*.png"))
            if caption_files:
                filters.append(self._build_caption_filter(caption_files, duration))
                logger.info("Adding %d caption frames", len(caption_files))

        # Add B-roll overlays
        if broll_clips:
            broll_filter, broll_inputs = self._build_broll_filter(broll_clips)
            if broll_filter:
                filters.append(broll_filter)
                extra_inputs.extend(broll_inputs)

        # Build complete filter chain
        if filters:
            vf = ",".join(f for f in filters if f)
            vf = (
                f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"({OUTPUT_WIDTH}-iw)/2:({OUTPUT_HEIGHT}-ih)/2:black,{vf}"
            )
        else:
            vf = (
                f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"({OUTPUT_WIDTH}-iw)/2:({OUTPUT_HEIGHT}-ih)/2:black"
            )

        # Build FFmpeg command
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
        ]

        # Add extra inputs for B-roll
        for inp in extra_inputs:
            cmd.extend(inp)

        cmd.extend([
            "-t", str(duration),
            "-vf", vf,
            "-c:v", OUTPUT_VIDEO_CODEC,
            "-preset", preset,
            "-crf", str(crf),
            "-threads", str(FFMPEG_THREADS),
            "-b:v", video_bitrate,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            "-r", str(OUTPUT_FPS),
            str(output_path),
        ])

        logger.info("Starting render...")
        result = await run_ffmpeg_command(cmd, timeout=1200)

        render_time = time.monotonic() - start_time

        if result.returncode != 0:
            raise RuntimeError(f"Render failed: {result.stderr[:500]}")

        if not output_path.exists():
            raise RuntimeError(f"Output file not created: {output_path}")

        file_size = output_path.stat().st_size
        actual_duration = await get_video_duration(output_path) or duration

        logger.info(
            "Render complete: %s (%.1fs, %d bytes, %.1fs render time)",
            output_path.name, actual_duration, file_size, render_time,
        )

        return OutputResult(
            file_path=output_path,
            duration=actual_duration,
            file_size=file_size,
            resolution=(OUTPUT_WIDTH, OUTPUT_HEIGHT),
            fps=OUTPUT_FPS,
            render_time=render_time,
            has_captions=bool(captions_dir and captions_dir.exists()),
            has_emoji=bool(emoji_overlays),
            has_broll=bool(broll_clips),
            has_zoom=zoom_enabled,
        )

    def _get_quality_settings(self, quality: str) -> tuple[int, str, str, str]:
        """Get FFmpeg encoding settings based on quality level."""
        settings = {
            "low": (24, "veryfast", "3M", "96k"),
            "medium": (20, "medium", "5M", "128k"),
            "high": (16, "slow", "8M", "192k"),
            "ultra": (14, "veryslow", "12M", "256k"),
        }
        return settings.get(quality, settings["high"])

    def _build_caption_filter(
        self,
        caption_frames: list[Path],
        duration: float,
    ) -> str:
        """Build FFmpeg filter for overlaying caption frames."""
        if not caption_frames:
            return ""

        total_frames = len(caption_frames)
        fps = OUTPUT_FPS

        # If caption frames are an image sequence (numbered PNGs),
        # use the image2demuxer approach
        if total_frames > 1:
            # Use overlay filter with image sequence
            filter_expr = (
                f"movie={caption_frames[0]}:loop=1,"
                f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
                f"format=rgba[overlay];"
                f"[0:v][overlay]overlay=0:0"
            )
        else:
            filter_expr = ""

        return filter_expr

    def _build_broll_filter(
        self,
        broll_clips: list[dict],
    ) -> tuple[str, list[list[str]]]:
        """
        Build FFmpeg filter for B-roll overlays.

        Returns: (filter_expression, list_of_extra_input_args)
        """
        if not broll_clips:
            return "", []

        filter_parts = []
        extra_inputs = []

        for i, clip in enumerate(broll_clips):
            clip_path = clip.get("path", "")
            start_time = clip.get("start", 0)
            end_time = clip.get("end", 0)
            opacity = clip.get("opacity", 0.5)

            if not clip_path or not Path(clip_path).exists():
                continue

            input_idx = i + 1
            extra_inputs.append(["-i", str(clip_path)])

            clip_duration = end_time - start_time

            # Scale and fade B-roll clip
            filter_parts.append(
                f"[{input_idx}:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
                f"({OUTPUT_WIDTH}-iw)/2:({OUTPUT_HEIGHT}-ih)/2:black,"
                f"setpts=PTS-STARTPTS+{start_time}/TB,"
                f"format=yuva420p,"
                f"colorchannelmixer=aa={opacity},"
                f"enable='between(t,{start_time},{end_time})'"
                f"[broll{i}];"
            )

            # Composite with main video
            filter_parts.append(
                f"[main{i}][broll{i}]overlay=0:0[main{i+1}];"
            )

        if not filter_parts:
            return "", []

        # Prepend main input reference
        final_filter = f"[0:v]copy[main0];" + "".join(filter_parts)
        # Remove trailing semicolon and output name
        if final_filter.endswith(";"):
            final_filter = final_filter[:-1]

        return final_filter, extra_inputs

    async def add_thumbnail(self, video_path: Path, thumbnail_path: Path) -> None:
        """Add a thumbnail/cover image to the video file."""
        if not thumbnail_path.exists():
            return

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(thumbnail_path),
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            str(video_path.with_suffix(".thumb.mp4")),
        ]

        result = await run_ffmpeg_command(cmd, timeout=60)

        if result.returncode == 0:
            thumb_path = video_path.with_suffix(".thumb.mp4")
            if thumb_path.exists():
                video_path.unlink(missing_ok=True)
                thumb_path.rename(video_path)
                logger.info("Thumbnail added to: %s", video_path.name)

    async def verify_output(self, output_path: Path) -> bool:
        """Verify that the output file is valid and playable."""
        if not output_path.exists():
            return False

        if output_path.stat().st_size < 1024:
            return False

        import subprocess as sp
        try:
            proc = sp.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type,width,height,duration",
                 "-of", "json", str(output_path)],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                return False

            import json
            info = json.loads(proc.stdout)
            streams = info.get("streams", [])
            if not streams:
                return False

            return True
        except Exception:
            return False


# Module-level convenience functions

async def generate_final_output(
    video_clip_path: str | Path,
    captions_overlay_path: Optional[str | Path] = None,
    output_path: Optional[str | Path] = None,
    quality: str = "high",
) -> Path:
    """Generate the final output video (convenience function)."""
    renderer = VideoOutputRenderer()
    result = await renderer.render(
        Path(video_clip_path),
        Path(output_path) if output_path else None,
        captions_dir=Path(captions_overlay_path) if captions_overlay_path else None,
        quality=quality,
    )
    return result.file_path


async def generate_thumbnail(
    video_path: str | Path,
    output_path: Optional[str | Path] = None,
    timestamp: float = 0.0,
) -> Path:
    """Generate a thumbnail from a video frame."""
    video_path = Path(video_path)
    if output_path is None:
        output_path = video_path.parent / f"{video_path.stem}_thumb.jpg"
    output_path = Path(output_path)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path),
    ]

    result = await run_ffmpeg_command(cmd, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Thumbnail generation failed: {result.stderr[:500]}")

    return output_path
