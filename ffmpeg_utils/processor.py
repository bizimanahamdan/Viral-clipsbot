"""
FFmpeg Processor — Advanced FFmpeg command builder and executor.

Provides high-level operations:
- Silence detection and removal
- Scene detection
- Video composition (compositing multiple clips)
- Audio mixing and normalization
- Speed adjustment
- Zoom effects
- Fade in/out transitions
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from configuration.config import (
    FFMPEG_THREADS, OUTPUT_FPS, OUTPUT_PIXEL_FORMAT,
    TEMP_DIR,
)
from ffmpeg_utils.commands import run_ffmpeg_command
from utilities.logging_config import get_logger

logger = get_logger("ffmpeg_utils.processor")


@dataclass
class SilenceSegment:
    """Detected silence segment."""
    start: float
    end: float
    duration: float
    is_silence: bool


@dataclass
class SceneSegment:
    """Detected scene segment."""
    start: float
    end: float
    scene_number: int


class FFmpegProcessor:
    """
    High-level FFmpeg operations for video processing.

    Wraps common FFmpeg operations into easy-to-use async methods.
    """

    def __init__(self, temp_dir: Optional[Path] = None):
        self.temp_dir = temp_dir or TEMP_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Silence Detection & Removal
    # -----------------------------------------------------------------------

    async def detect_silence(
        self,
        audio_path: Path,
        threshold: float = -40.0,
        min_duration: float = 0.5,
    ) -> list[SilenceSegment]:
        """
        Detect silence segments in an audio file.

        Uses FFmpeg's silencedetect filter.

        Args:
            audio_path: Path to audio file.
            threshold: Noise tolerance in dB (default -40dB).
            min_duration: Minimum silence duration in seconds.

        Returns:
            List of SilenceSegment objects.
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
            "-f", "null", "-",
        ]

        result = await run_ffmpeg_command(cmd, timeout=300)
        stderr = result.stderr

        # Parse silence detection output
        segments = []
        silence_start = None

        for line in stderr.split("\n"):
            if "silence_start:" in line:
                try:
                    val = line.split("silence_start:")[1].strip()
                    silence_start = float(val)
                except ValueError:
                    pass
            elif "silence_end:" in line and silence_start is not None:
                try:
                    parts = line.split("|")
                    end_val = parts[0].split("silence_end:")[1].strip()
                    duration_val = parts[1].split("silence_duration:")[1].strip()
                    end_time = float(end_val)
                    duration = float(duration_val)

                    segments.append(SilenceSegment(
                        start=silence_start,
                        end=end_time,
                        duration=duration,
                        is_silence=True,
                    ))
                    silence_start = None
                except (ValueError, IndexError):
                    pass

        # If silence started but didn't end, it goes to the end of the file
        if silence_start is not None:
            segments.append(SilenceSegment(
                start=silence_start,
                end=-1,  # Unknown end
                duration=0,
                is_silence=True,
            ))

        logger.info("Detected %d silence segments", len(segments))
        return segments

    async def remove_silence(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        threshold: float = -40.0,
        silence_duration: float = 0.5,
        padding: float = 0.1,
    ) -> Path:
        """
        Remove silence from a video/audio file.

        Keeps a small padding of silence before and after speech
        for natural-sounding results.

        Args:
            input_path: Input file path.
            output_path: Output file path.
            threshold: Silence detection threshold in dB.
            silence_duration: Minimum silence to remove.
            padding: Keep this much silence around speech.

        Returns:
            Path to output file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_no_silence.mp4"
        output_path = Path(output_path)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", (
                f"silenceremove=stop_periods=-1:"
                f"stop_duration={silence_duration}:"
                f"stop_threshold={threshold}dB"
            ),
            "-preset", "fast",
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Silence removal failed: {result.stderr[:300]}")

        logger.info("Silence removed: %s -> %s", input_path.name, output_path.name)
        return output_path

    # -----------------------------------------------------------------------
    # Scene Detection
    # -----------------------------------------------------------------------

    async def detect_scenes(
        self,
        video_path: Path,
        threshold: float = 0.3,
    ) -> list[SceneSegment]:
        """
        Detect scene changes in a video.

        Uses FFmpeg's select filter with scene scoring.

        Args:
            video_path: Input video path.
            threshold: Scene change threshold (0-1).

        Returns:
            List of SceneSegment objects.
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"select=gt(scene,{threshold}),showinfo",
            "-vsync", "0",
            "-frames:v", "1000",  # Limit to first 1000 scene changes
            "-f", "null", "-",
        ]

        result = await run_ffmpeg_command(cmd, timeout=300)
        stderr = result.stderr

        scenes = []
        current_scene_start = 0.0
        scene_number = 0

        for line in stderr.split("\n"):
            if "pts_time:" in line and "scene" in line:
                try:
                    time_str = line.split("pts_time:")[1].split()[0]
                    scene_time = float(time_str)

                    if scene_number > 0:
                        scenes.append(SceneSegment(
                            start=current_scene_start,
                            end=scene_time,
                            scene_number=scene_number,
                        ))

                    current_scene_start = scene_time
                    scene_number += 1
                except (ValueError, IndexError):
                    pass

        logger.info("Detected %d scene changes", len(scenes))
        return scenes

    # -----------------------------------------------------------------------
    # Video Composition
    # -----------------------------------------------------------------------

    async def concat_clips(
        self,
        clip_paths: list[Path],
        output_path: Optional[Path] = None,
        crossfade: bool = True,
        crossfade_duration: float = 0.5,
    ) -> Path:
        """
        Concatenate multiple video clips.

        Args:
            clip_paths: List of clip paths to concatenate.
            output_path: Output file path.
            crossfade: Whether to add crossfade transitions.
            crossfade_duration: Duration of each crossfade.

        Returns:
            Path to output file.
        """
        if not clip_paths:
            raise ValueError("No clips to concatenate")

        if output_path is None:
            output_path = self.temp_dir / "concatenated.mp4"
        output_path = Path(output_path)

        if len(clip_paths) == 1:
            # Single clip — just copy
            cmd = [
                "ffmpeg", "-y",
                "-i", str(clip_paths[0]),
                "-c", "copy",
                str(output_path),
            ]
        elif crossfade and len(clip_paths) > 1:
            # Crossfade concatenation using xfade
            cmd = self._build_xfade_command(
                clip_paths, output_path, crossfade_duration,
            )
        else:
            # Simple concatenation
            concat_file = self.temp_dir / "concat_list.txt"
            with open(concat_file, "w") as f:
                for clip in clip_paths:
                    f.write(f"file '{clip}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Concat failed: {result.stderr[:300]}")

        logger.info("Concatenated %d clips -> %s", len(clip_paths), output_path.name)
        return output_path

    def _build_xfade_command(
        self,
        clip_paths: list[Path],
        output_path: Path,
        crossfade_duration: float,
    ) -> list[str]:
        """Build FFmpeg xfade command for smooth concatenation."""
        cmd = ["ffmpeg", "-y"]

        # Add all inputs
        for clip in clip_paths:
            cmd.extend(["-i", str(clip)])

        # Build filter complex for crossfade
        filter_parts = []
        last_output = "0:v"

        for i in range(len(clip_paths) - 1):
            if i == 0:
                first_input = "0:v"
            else:
                first_input = f"vfade{i-1}"

            second_input = f"{i+1}:v"
            output_label = f"vfade{i}"

            filter_parts.append(
                f"[{first_input}][{second_input}]xfade=transition=fade:"
                f"duration={crossfade_duration}:offset={i * 10}"
                f"[{output_label}]"
            )

        final_video = filter_parts[-1].split("]")[-2] if filter_parts else "0:v"

        # Audio mix
        audio_filter = ""
        if len(clip_paths) > 1:
            audio_inputs = ",".join(f"{i}:a" for i in range(len(clip_paths)))
            audio_filter = f"[{audio_inputs}]amix=inputs={len(clip_paths)}[a]"

        full_filter = ";".join(filter_parts)
        if audio_filter:
            full_filter += f";{audio_filter}"

        cmd.extend(["-filter_complex", full_filter])
        cmd.extend(["-map", final_video, "-map", "[a]" if audio_filter else "0:a"])
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23"])
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        cmd.append(str(output_path))

        return cmd

    # -----------------------------------------------------------------------
    # Audio Processing
    # -----------------------------------------------------------------------

    async def normalize_audio(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        target_loudness: float = -16.0,
    ) -> Path:
        """
        Normalize audio to target loudness (LUFS).

        Args:
            input_path: Input file path.
            output_path: Output file path.
            target_loudness: Target loudness in LUFS (default -16).

        Returns:
            Path to output file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_normalized.mp4"
        output_path = Path(output_path)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", f"loudnorm=I={target_loudness}:TP=-1.5:LRA=11",
            "-c:v", "copy",
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Audio normalization failed: {result.stderr[:300]}")

        logger.info("Audio normalized: %s -> %s", input_path.name, output_path.name)
        return output_path

    async def adjust_speed(
        self,
        input_path: Path,
        speed: float = 1.0,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Adjust video playback speed.

        Args:
            input_path: Input file path.
            speed: Playback speed (1.0 = normal, 1.5 = 1.5x faster).
            output_path: Output file path.

        Returns:
            Path to output file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_speed{speed:.1f}x.mp4"
        output_path = Path(output_path)

        # Clamp speed to valid range for FFmpeg
        speed = max(0.25, min(speed, 100.0))
        audio_speed = 1.0 / speed

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter_complex",
            f"[0:v]setpts={1/speed}*PTS[v];"
            f"[0:a]atempo={audio_speed}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        # For extreme speeds, use different audio approach
        if speed > 2.0:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-filter_complex",
                f"[0:v]setpts={1/speed}*PTS[v];"
                f"[0:a]atempo=2,atempo={audio_speed/2}[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-r", str(OUTPUT_FPS),
                str(output_path),
            ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Speed adjustment failed: {result.stderr[:300]}")

        logger.info("Speed adjusted: %s %.1fx -> %s", input_path.name, speed, output_path.name)
        return output_path

    # -----------------------------------------------------------------------
    # Zoom Effects
    # -----------------------------------------------------------------------

    async def apply_zoom_effect(
        self,
        input_path: Path,
        zoom_points: list[tuple[float, float]],
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Apply zoom effects at specified timestamps.

        Args:
            input_path: Input video path.
            zoom_points: List of (time, intensity) tuples.
            output_path: Output file path.

        Returns:
            Path to output file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_zoomed.mp4"
        output_path = Path(output_path)

        if not zoom_points:
            # No zoom points — just copy
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-c", "copy",
                str(output_path),
            ]
        else:
            # Build zoom filter
            zoom_expressions = []
            for time_val, intensity in zoom_points:
                zoom_expressions.append(
                    f"if(between(t,{time_val},{time_val + 1.0}),"
                    f"1+0.1*{intensity}*(t-{time_val}),1)"
                )

            zoom_expr = "*".join(zoom_expressions) if len(zoom_expressions) == 1 else zoom_expressions[0]

            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vf", f"zoompan=z='{zoom_expr}':d=1:s=1080x1920:fps={OUTPUT_FPS}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "copy",
                str(output_path),
            ]

        result = await run_ffmpeg_command(cmd, timeout=1200)
        if result.returncode != 0:
            raise RuntimeError(f"Zoom effect failed: {result.stderr[:300]}")

        logger.info("Zoom effect applied: %s -> %s", input_path.name, output_path.name)
        return output_path

    # -----------------------------------------------------------------------
    # Fade Transitions
    # -----------------------------------------------------------------------

    async def apply_fade(
        self,
        input_path: Path,
        fade_in: float = 0.5,
        fade_out: float = 0.5,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Apply fade in/out transitions.

        Args:
            input_path: Input video path.
            fade_in: Duration of fade in (seconds).
            fade_out: Duration of fade out (seconds).
            output_path: Output file path.

        Returns:
            Path to output file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_faded.mp4"
        output_path = Path(output_path)

        # Get duration
        from ffmpeg_utils.commands import get_video_duration
        duration = await get_video_duration(input_path)
        if not duration:
            duration = 60.0

        fade_out_start = max(0, duration - fade_out)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf",
            f"fade=t=in:st=0:d={fade_in},"
            f"fade=t=out:st={fade_out_start}:d={fade_out}",
            "-af",
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start}:d={fade_out}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Fade effect failed: {result.stderr[:300]}")

        logger.info("Fade applied: %s -> %s", input_path.name, output_path.name)
        return output_path
