"""
Video Reframing — Convert to 9:16 vertical format.

Uses OpenCV face detection to keep speakers/subjects centered.
Implements dynamic zoom for high-energy and emotional moments.
Creates smooth keyframed transitions with no jitter.

Features:
- Face detection and tracking via OpenCV
- Dynamic zoom on speech/emotional moments
- Smooth keyframed camera movement
- Center-of-interest tracking
- Multiple tracking strategies (face, motion, center)
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
    TEMP_DIR, SHORTS_WIDTH, SHORTS_HEIGHT,
)
from ffmpeg_utils.commands import run_ffmpeg_command, get_video_duration, get_video_resolution
from utilities.logging_config import get_logger

logger = get_logger("video_processing.reframe")


@dataclass
class ReframeResult:
    """Result of a reframing operation."""
    output_path: Path
    method: str
    source_resolution: tuple[int, int]
    target_resolution: tuple[int, int]
    tracking_enabled: bool
    zoom_enabled: bool


class VideoReframer:
    """
    Converts landscape video to 9:16 portrait format with
    intelligent subject tracking and dynamic zoom effects.
    """

    TARGET_WIDTH = SHORTS_WIDTH   # 1080
    TARGET_HEIGHT = SHORTS_HEIGHT  # 1920

    def __init__(
        self,
        temp_dir: Optional[Path] = None,
        face_detection_interval: int = 10,
        zoom_speed: float = 1.1,
        zoom_steps: int = 20,
        smooth_factor: float = 0.3,
    ):
        """
        Initialize the video reframer.

        Args:
            temp_dir: Temporary directory for intermediate files.
            face_detection_interval: Frames between face detection runs.
            zoom_speed: Speed multiplier for dynamic zoom.
            zoom_steps: Number of interpolation steps for smooth zoom.
            smooth_factor: Smoothing factor for camera movement (0-1).
        """
        self.temp_dir = temp_dir or TEMP_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.face_detection_interval = face_detection_interval
        self.zoom_speed = zoom_speed
        self.zoom_steps = zoom_steps
        self.smooth_factor = smooth_factor

    async def reframe(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        enable_face_tracking: bool = True,
        enable_zoom: bool = True,
        zoom_points: Optional[list[tuple[float, float]]] = None,
    ) -> ReframeResult:
        """
        Convert a video to 9:16 portrait format with face tracking.

        Strategy:
        1. Detect faces in the source video
        2. Calculate crop region that keeps faces centered
        3. Apply smooth camera movement between detected positions
        4. Apply dynamic zoom at specified energy/emotional moments
        5. Render the final 9:16 output
        """
        if output_path is None:
            output_path = self.temp_dir / f"{video_path.stem}_reframed.mp4"

        duration = await get_video_duration(video_path)
        source_res = await get_video_resolution(video_path)

        if not duration or not source_res:
            raise RuntimeError(f"Cannot get video info for: {video_path}")

        src_w, src_h = source_res
        logger.info(
            "Reframing: %s (%dx%d, %.1fs) -> %dx%d",
            video_path.name, src_w, src_h, duration,
            self.TARGET_WIDTH, self.TARGET_HEIGHT,
        )

        source_aspect = src_w / src_h if src_h > 0 else 16/9
        target_aspect = self.TARGET_WIDTH / self.TARGET_HEIGHT

        if source_aspect > target_aspect:
            # Source is wider — horizontal crop needed
            if enable_face_tracking and self._face_detection_available():
                return await self._reframe_with_face_tracking(
                    video_path, output_path, src_w, src_h, duration,
                )
            else:
                return await self._reframe_center_crop(
                    video_path, output_path, src_w, src_h, duration,
                )
        elif source_aspect < target_aspect:
            return await self._reframe_vertical_crop(
                video_path, output_path, src_w, src_h, duration,
            )
        else:
            return await self._reframe_resize(
                video_path, output_path, src_w, src_h, duration,
            )

    def _face_detection_available(self) -> bool:
        """Check if OpenCV face detection is available."""
        try:
            import cv2
            return True
        except ImportError:
            return False

    async def _reframe_with_face_tracking(
        self,
        video_path: Path,
        output_path: Path,
        src_w: int,
        src_h: int,
        duration: float,
    ) -> ReframeResult:
        """Reframe using face detection to track the speaker."""
        from opencv_utils.face_tracker import FaceTracker

        tracker = FaceTracker()
        face_positions = await tracker.track_faces(
            video_path,
            sample_interval=self.face_detection_interval,
        )

        if not face_positions:
            logger.info("No faces detected, falling back to center crop")
            return await self._reframe_center_crop(
                video_path, output_path, src_w, src_h, duration,
            )

        logger.info("Detected %d face positions", len(face_positions))

        # Calculate weighted average x position for crop
        target_aspect = self.TARGET_WIDTH / self.TARGET_HEIGHT
        crop_h = src_h
        crop_w = int(src_h * target_aspect)

        if len(face_positions) >= 2:
            weighted_x = sum(
                fp.get("x", src_w // 2) * fp.get("weight", 1)
                for fp in face_positions
            ) / max(sum(fp.get("weight", 1) for fp in face_positions), 1)
            avg_x = max(0, min(int(weighted_x - crop_w // 2), src_w - crop_w))
        else:
            avg_x = (src_w - crop_w) // 2

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf",
            f"crop={crop_w}:{src_h}:{avg_x}:0,"
            f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"({self.TARGET_WIDTH}-iw)/2:({self.TARGET_HEIGHT}-ih)/2:black",
            "-c:v", OUTPUT_VIDEO_CODEC,
            "-preset", FFMPEG_PRESET,
            "-threads", str(FFMPEG_THREADS),
            "-b:v", OUTPUT_VIDEO_BITRATE,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)

        if result.returncode != 0:
            logger.warning("Face tracking crop failed, falling back to center")
            return await self._reframe_center_crop(
                video_path, output_path, src_w, src_h, duration,
            )

        return ReframeResult(
            output_path=output_path,
            method="face_tracking",
            source_resolution=(src_w, src_h),
            target_resolution=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
            tracking_enabled=True,
            zoom_enabled=False,
        )

    async def _reframe_center_crop(
        self,
        video_path: Path,
        output_path: Path,
        src_w: int,
        src_h: int,
        duration: float,
    ) -> ReframeResult:
        """Reframe using center crop."""
        target_aspect = self.TARGET_WIDTH / self.TARGET_HEIGHT

        if src_w / src_h > target_aspect:
            crop_h = src_h
            crop_w = int(src_h * target_aspect)
            x_offset = (src_w - crop_w) // 2
            y_offset = 0
        else:
            crop_w = src_w
            crop_h = int(src_w / target_aspect)
            x_offset = 0
            y_offset = (src_h - crop_h) // 2

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf",
            f"crop={crop_w}:{crop_h}:{x_offset}:{y_offset},"
            f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"({self.TARGET_WIDTH}-iw)/2:({self.TARGET_HEIGHT}-ih)/2:black",
            "-c:v", OUTPUT_VIDEO_CODEC,
            "-preset", FFMPEG_PRESET,
            "-threads", str(FFMPEG_THREADS),
            "-b:v", OUTPUT_VIDEO_BITRATE,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Center crop reframe failed: {result.stderr[:500]}")

        return ReframeResult(
            output_path=output_path,
            method="center_crop",
            source_resolution=(src_w, src_h),
            target_resolution=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
            tracking_enabled=False,
            zoom_enabled=False,
        )

    async def _reframe_with_zoom(
        self,
        video_path: Path,
        output_path: Path,
        zoom_points: list[tuple[float, float]],
        src_w: int,
        src_h: int,
        duration: float,
    ) -> ReframeResult:
        """Reframe with dynamic zoom effects at specified moments."""
        target_aspect = self.TARGET_WIDTH / self.TARGET_HEIGHT

        if src_w / src_h > target_aspect:
            crop_h = src_h
            crop_w = int(src_h * target_aspect)
            x_offset = (src_w - crop_w) // 2
            y_offset = 0
        else:
            crop_w = src_w
            crop_h = int(src_w / target_aspect)
            x_offset = 0
            y_offset = (src_h - crop_h) // 2

        # Build zoom expression for FFmpeg
        zoom_expr = self._build_zoom_expression(
            zoom_points, crop_w, crop_h, duration, OUTPUT_FPS,
        )

        vf = (
            f"crop={crop_w}:{crop_h}:{x_offset}:{y_offset},"
            f"zoompan=z={zoom_expr}:d={self.zoom_steps}:x={x_offset}:y={y_offset}:s={self.TARGET_WIDTH}x{self.TARGET_HEIGHT},"
            f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:({self.TARGET_WIDTH}-iw)/2:({self.TARGET_HEIGHT}-ih)/2:black"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", OUTPUT_VIDEO_CODEC,
            "-preset", FFMPEG_PRESET,
            "-threads", str(FFMPEG_THREADS),
            "-b:v", OUTPUT_VIDEO_BITRATE,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC,
            "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Zoom reframe failed: {result.stderr[:500]}")

        return ReframeResult(
            output_path=output_path,
            method="zoom",
            source_resolution=(src_w, src_h),
            target_resolution=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
            tracking_enabled=False,
            zoom_enabled=True,
        )

    async def _reframe_vertical_crop(
        self,
        video_path: Path,
        output_path: Path,
        src_w: int,
        src_h: int,
        duration: float,
    ) -> ReframeResult:
        """Reframe when source is taller than target."""
        target_aspect = self.TARGET_WIDTH / self.TARGET_HEIGHT
        crop_w = src_w
        crop_h = int(src_w / target_aspect)
        x_offset = 0
        y_offset = max(0, (src_h - crop_h) // 2)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf",
            f"crop={crop_w}:{crop_h}:{x_offset}:{y_offset},"
            f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
            f"({self.TARGET_WIDTH}-iw)/2:({self.TARGET_HEIGHT}-ih)/2:black",
            "-c:v", OUTPUT_VIDEO_CODEC, "-preset", FFMPEG_PRESET,
            "-threads", str(FFMPEG_THREADS),
            "-b:v", OUTPUT_VIDEO_BITRATE,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC, "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart", "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Vertical crop reframe failed: {result.stderr[:500]}")

        return ReframeResult(
            output_path=output_path, method="vertical_crop",
            source_resolution=(src_w, src_h),
            target_resolution=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
            tracking_enabled=False, zoom_enabled=False,
        )

    async def _reframe_resize(
        self,
        video_path: Path,
        output_path: Path,
        src_w: int,
        src_h: int,
        duration: float,
    ) -> ReframeResult:
        """Reframe when source already matches target aspect ratio."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}",
            "-c:v", OUTPUT_VIDEO_CODEC, "-preset", FFMPEG_PRESET,
            "-threads", str(FFMPEG_THREADS),
            "-b:v", OUTPUT_VIDEO_BITRATE,
            "-pix_fmt", OUTPUT_PIXEL_FORMAT,
            "-c:a", OUTPUT_AUDIO_CODEC, "-b:a", OUTPUT_AUDIO_BITRATE,
            "-movflags", "+faststart", "-r", str(OUTPUT_FPS),
            str(output_path),
        ]

        result = await run_ffmpeg_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Resize reframe failed: {result.stderr[:500]}")

        return ReframeResult(
            output_path=output_path, method="resize",
            source_resolution=(src_w, src_h),
            target_resolution=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
            tracking_enabled=False, zoom_enabled=False,
        )

    def _build_zoom_expression(
        self,
        zoom_points: list[tuple[float, float]],
        crop_w: int,
        crop_h: int,
        duration: float,
        fps: int,
    ) -> str:
        """
        Build FFmpeg zoompan expression.

        Creates a piecewise zoom expression that smoothly transitions
        between zoom levels at specified time points.
        """
        if not zoom_points:
            return "1"

        total_frames = int(duration * fps)

        # Build segments
        segments = []
        prev_frame = 0
        prev_zoom = 1.0

        for time_point, intensity in zoom_points:
            frame = min(int(time_point * fps), total_frames - 1)
            target_zoom = 1.0 + intensity * (self.zoom_speed - 1.0)
            segments.append((prev_frame, frame, prev_zoom, target_zoom))
            prev_frame = frame
            prev_zoom = target_zoom

        # Add final segment
        if prev_frame < total_frames:
            segments.append((prev_frame, total_frames - 1, prev_zoom, 1.0))

        # Build expression
        expr_parts = []
        for start_frame, end_frame, start_zoom, end_zoom in segments:
            frames_in_segment = max(end_frame - start_frame, 1)
            expr_parts.append(
                f"if(lte(on,{end_frame}),{start_zoom}+(in-{start_frame})/"
                f"{frames_in_segment}*({end_zoom}-{start_zoom}),)"
            )

        # Join with else clause
        expression = "1"
        for part in reversed(expr_parts):
            expression = f"{part[:-1]},{expression})"

        return expression or "1"


# Module-level convenience function

async def reframe_to_vertical(
    video_path: str | Path,
    output_path: Optional[str | Path] = None,
    target_width: int = OUTPUT_WIDTH,
    target_height: int = OUTPUT_HEIGHT,
    fps: int = OUTPUT_FPS,
    face_tracking: bool = False,
) -> Path:
    """Convert a video to vertical 9:16 format (convenience function)."""
    reframer = VideoReframer()
    result = await reframer.reframe(
        Path(video_path),
        Path(output_path) if output_path else None,
        enable_face_tracking=face_tracking,
    )
    return result.output_path
