"""
FFmpeg command builder and executor utilities.

Provides a high-level interface for common FFmpeg operations
used throughout the video processing pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from configuration.config import FFMPEG_THREADS
from utilities.logging_config import get_logger

logger = get_logger("ffmpeg_utils.commands")


async def run_ffmpeg(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """
    Execute an FFmpeg command and return (returncode, stdout, stderr).

    Args:
        cmd: FFmpeg command arguments.
        timeout: Maximum execution time in seconds.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, stdout.decode(), stderr.decode()
    except asyncio.TimeoutError:
        process.kill()
        return -1, "", "FFmpeg command timed out"
    except Exception as e:
        return -1, "", str(e)


async def get_video_metadata(video_path: str | Path) -> dict:
    """
    Get video metadata using ffprobe.

    Returns:
        dict with width, height, duration, fps, codec, etc.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    returncode, stdout, stderr = await run_ffmpeg(cmd)

    if returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr[:200]}")

    data = json.loads(stdout)

    # Extract video stream info
    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    format_info = data.get("format", {})

    return {
        "width": int(video_stream.get("width", 0)) if video_stream else 0,
        "height": int(video_stream.get("height", 0)) if video_stream else 0,
        "fps": _parse_fps(video_stream) if video_stream else 30,
        "duration": float(format_info.get("duration", 0)),
        "video_codec": video_stream.get("codec_name", "") if video_stream else "",
        "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
        "bitrate": int(format_info.get("bit_rate", 0)),
        "file_size": int(format_info.get("size", 0)),
        "has_audio": audio_stream is not None,
    }


async def detect_scene_changes(
    video_path: str | Path,
    threshold: float = 0.3,
) -> list[float]:
    """
    Detect scene changes in a video using FFmpeg's scenecut filter.

    Returns:
        List of timestamps (in seconds) where scene changes occur.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]

    returncode, stdout, stderr = await run_ffmpeg(cmd)

    # Parse scene change timestamps from stderr
    timestamps = []
    for line in stderr.split("\n"):
        if "pts_time:" in line:
            try:
                pts = float(line.split("pts_time:")[1].split()[0])
                timestamps.append(pts)
            except (ValueError, IndexError):
                pass

    logger.info("Detected %d scene changes in %s", len(timestamps), Path(video_path).name)
    return timestamps


async def extract_frames(
    video_path: str | Path,
    output_dir: str | Path,
    fps: float = 1.0,
    start_time: float = 0,
    duration: Optional[float] = None,
) -> list[Path]:
    """
    Extract frames from a video at a given frame rate.

    Args:
        video_path: Path to the video.
        output_dir: Directory for output frames.
        fps: Frames per second to extract.
        start_time: Start time in seconds.
        duration: Duration to extract (None = entire video).

    Returns:
        List of paths to extracted frames.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-ss", str(start_time)]

    if duration:
        cmd.extend(["-t", str(duration)])

    cmd.extend([
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        str(output_dir / "frame_%06d.png"),
    ])

    returncode, stdout, stderr = await run_ffmpeg(cmd)

    if returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {stderr[:200]}")

    frames = sorted(output_dir.glob("frame_*.png"))
    logger.info("Extracted %d frames from %s", len(frames), Path(video_path).name)
    return frames


async def add_audio_to_video(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Combine a video (without audio) with an audio file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]

    returncode, stdout, stderr = await run_ffmpeg(cmd)

    if returncode != 0:
        raise RuntimeError(f"Audio add failed: {stderr[:200]}")

    return output_path


async def overlay_image(
    video_path: str | Path,
    image_path: str | Path,
    output_path: str | Path,
    position: str = "center",
    x: int = 0,
    y: int = 0,
) -> Path:
    """Overlay an image on a video."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if position == "center":
        filter_str = f"overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    else:
        filter_str = f"overlay={x}:{y}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(image_path),
        "-filter_complex", filter_str,
        "-c:v", "libx264",
        "-c:a", "copy",
        str(output_path),
    ]

    returncode, stdout, stderr = await run_ffmpeg(cmd)

    if returncode != 0:
        raise RuntimeError(f"Overlay failed: {stderr[:200]}")

    return output_path


# Backwards-compatible aliases


async def run_ffmpeg_command(cmd: list[str], timeout: int = 600) -> "_CmdResult":
    """
    Execute an FFmpeg command and return a result object.

    This is a backwards-compatible alias for run_ffmpeg that returns
    an object with .returncode and .stderr attributes instead of a tuple.
    """
    rc, stdout, stderr = await run_ffmpeg(cmd, timeout)
    return _CmdResult(returncode=rc, stdout=stdout, stderr=stderr)


class _CmdResult:
    """Simple result object for FFmpeg command execution."""
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


async def get_video_duration(video_path: str | Path) -> Optional[float]:
    """Get the duration of a video file in seconds."""
    meta = await get_video_metadata(video_path)
    return meta.get("duration", 0.0) or None


async def get_video_resolution(video_path: str | Path) -> tuple[int, int]:
    """Get the resolution (width, height) of a video file."""
    meta = await get_video_metadata(video_path)
    return meta.get("width", 0), meta.get("height", 0)


def _parse_fps(stream: dict) -> float:
    """Parse FPS from a video stream dict."""
    fps_str = stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        return float(num) / float(den) if float(den) > 0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0
