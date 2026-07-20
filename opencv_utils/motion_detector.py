"""
Motion Detector — Detect motion intensity, scene changes, and camera movement.

Uses OpenCV to analyze video frames for:
- Motion intensity (frame differencing + optical flow)
- Scene change detection (histogram comparison)
- Camera movement estimation
- Energy level estimation

Used by the pipeline to determine zoom points, B-roll placement,
and engagement markers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from configuration.config import OUTPUT_FPS
from utilities.logging_config import get_logger

logger = get_logger("opencv_utils.motion_detector")

# Default constants
SCENE_CHANGE_THRESHOLD: float = 0.35
MOTION_INTENSITY_THRESHOLD: float = 0.15
MIN_ZOOM_SPACING_SECONDS: float = 3.0
SAMPLE_FPS: int = 10  # frames to sample per second for analysis


@dataclass
class MotionFrame:
    """Motion analysis result for a single frame."""
    frame_number: int
    timestamp: float
    motion_intensity: float = 0.0
    is_scene_change: bool = False
    camera_movement: float = 0.0
    brightness: float = 0.0
    energy_level: float = 0.0


@dataclass
class MotionAnalysis:
    """Complete motion analysis of a video."""
    frames: list[MotionFrame] = field(default_factory=list)
    scene_change_count: int = 0
    average_motion: float = 0.0
    average_energy: float = 0.0
    peak_motion_frame: int = 0
    peak_motion_time: float = 0.0
    video_duration: float = 0.0
    video_fps: float = OUTPUT_FPS


class MotionDetector:
    """
    Detects motion between consecutive frames using
    frame differencing and optical flow.
    """

    SCENE_CHANGE_THRESHOLD = 0.7
    HIGH_MOTION_THRESHOLD = 0.6
    LOW_MOTION_THRESHOLD = 0.15

    def __init__(
        self,
        threshold: int = 25,
        min_area: int = 500,
        scene_change_threshold: float = SCENE_CHANGE_THRESHOLD,
        sample_interval: int = 5,
        histogram_bins: int = 64,
    ):
        self.threshold = threshold
        self.min_area = min_area
        self.scene_change_threshold = scene_change_threshold
        self.sample_interval = sample_interval
        self.histogram_bins = histogram_bins
        self._prev_frame: Optional[np.ndarray] = None

    # -----------------------------------------------------------------------
    # Single-Frame Detection
    # -----------------------------------------------------------------------

    def detect_motion(self, frame: np.ndarray) -> dict:
        """
        Detect motion in a frame compared to the previous frame.

        Returns dict with has_motion, motion_area, motion_level, contour_count.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_frame is None:
            self._prev_frame = gray
            return {"has_motion": False, "motion_area": 0, "motion_level": 0.0}

        delta = cv2.absdiff(self._prev_frame, gray)
        thresh = cv2.threshold(delta, self.threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(
            thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )

        motion_area = sum(
            cv2.contourArea(c) for c in contours if cv2.contourArea(c) > self.min_area
        )
        frame_area = frame.shape[0] * frame.shape[1]
        motion_level = motion_area / frame_area if frame_area > 0 else 0.0

        self._prev_frame = gray

        return {
            "has_motion": motion_level > 0.01,
            "motion_area": motion_area,
            "motion_level": motion_level,
            "contour_count": len(contours),
        }

    def reset(self) -> None:
        """Reset the detector state."""
        self._prev_frame = None

    # -----------------------------------------------------------------------
    # Full Video Analysis
    # -----------------------------------------------------------------------

    async def analyze_video(
        self,
        video_path: Path,
        max_frames: Optional[int] = None,
    ) -> MotionAnalysis:
        """
        Analyze the entire video for motion and scene changes.

        Args:
            video_path: Path to the video file.
            max_frames: Maximum frames to analyze.

        Returns:
            MotionAnalysis with frame-by-frame results.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Cannot open video for motion analysis: %s", video_path)
            return MotionAnalysis()

        fps = cap.get(cv2.CAP_PROP_FPS) or OUTPUT_FPS
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        frame_step = max(1, int(fps * self.sample_interval))
        if max_frames:
            frame_step = max(frame_step, total_frames // max_frames)

        logger.info(
            "Analyzing motion: %d frames, %.1f fps, %.1fs, step=%d",
            total_frames, fps, duration, frame_step,
        )

        motion_frames = []
        prev_histogram = None
        prev_gray = None
        scene_change_count = 0
        peak_motion = 0.0
        peak_frame = 0

        processed = 0
        frame_idx = 0

        while True:
            target_frame = processed * frame_step
            if target_frame >= total_frames:
                break

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Histogram for scene change
            hist = cv2.calcHist([gray], [0], None, [self.histogram_bins], [0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

            is_scene_change = False
            if prev_histogram is not None:
                diff = cv2.compareHist(hist, prev_histogram, cv2.HISTCMP_CORREL)
                if diff < (1 - self.scene_change_threshold):
                    is_scene_change = True
                    scene_change_count += 1

            # Motion intensity (frame differencing)
            motion_intensity = 0.0
            if prev_gray is not None:
                diff_frame = cv2.absdiff(prev_gray, gray)
                motion_intensity = float(np.mean(diff_frame)) / 255.0

            # Camera movement
            camera_movement = self._estimate_camera_movement(prev_gray, gray) if prev_gray is not None else 0.0

            # Brightness
            brightness = float(np.mean(gray)) / 255.0

            # Energy level
            energy_level = min(1.0, motion_intensity * 2 + (1 - abs(brightness - 0.5) * 2) * 0.5)

            timestamp = frame_idx * self.sample_interval

            motion_frames.append(MotionFrame(
                frame_number=frame_idx,
                timestamp=timestamp,
                motion_intensity=motion_intensity,
                is_scene_change=is_scene_change,
                camera_movement=camera_movement,
                brightness=brightness,
                energy_level=energy_level,
            ))

            if motion_intensity > peak_motion:
                peak_motion = motion_intensity
                peak_frame = frame_idx

            prev_histogram = hist
            prev_gray = gray.copy()
            frame_idx += 1
            processed += 1

        cap.release()

        avg_motion = float(np.mean([f.motion_intensity for f in motion_frames])) if motion_frames else 0
        avg_energy = float(np.mean([f.energy_level for f in motion_frames])) if motion_frames else 0

        logger.info(
            "Motion analysis complete: %d frames, %d scene changes, avg motion=%.3f",
            len(motion_frames), scene_change_count, avg_motion,
        )

        return MotionAnalysis(
            frames=motion_frames,
            scene_change_count=scene_change_count,
            average_motion=avg_motion,
            average_energy=avg_energy,
            peak_motion_frame=peak_frame,
            peak_motion_time=peak_frame * self.sample_interval,
            video_duration=duration,
            video_fps=fps,
        )

    def _estimate_camera_movement(
        self,
        prev_gray: Optional[np.ndarray],
        curr_gray: np.ndarray,
        max_corners: int = 100,
    ) -> float:
        """Estimate camera movement using optical flow. Returns 0.0-1.0."""
        if prev_gray is None:
            return 0.0

        corners = cv2.goodFeaturesToTrack(
            prev_gray, maxCorners=max_corners,
            qualityLevel=0.01, minDistance=30,
        )

        if corners is None or len(corners) < 5:
            return 0.0

        curr_corners, status, _ = cv2.calcOpticalFlowPyrLK(
            prev_gray, curr_gray, corners, None,
        )

        if curr_corners is None or status is None:
            return 0.0

        valid_prev = corners[status.ravel() == 1]
        valid_curr = curr_corners[status.ravel() == 1]

        if len(valid_prev) < 5:
            return 0.0

        displacements = np.sqrt(np.sum((valid_curr - valid_prev) ** 2, axis=2))
        avg_displacement = float(np.mean(displacements))

        return min(1.0, avg_displacement / 50.0)


# ---------------------------------------------------------------------------
# Standalone Functions
# ---------------------------------------------------------------------------

def detect_scene_change(
    frame1: np.ndarray,
    frame2: np.ndarray,
    threshold: float = 0.3,
) -> bool:
    """Detect if a scene change occurred between two frames using histogram comparison."""
    hist1 = cv2.calcHist([frame1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist2 = cv2.calcHist([frame2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist1 = cv2.normalize(hist1, hist1).flatten()
    hist2 = cv2.normalize(hist2, hist2).flatten()
    similarity = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    return similarity < threshold


def calculate_camera_movement(
    frames: list[np.ndarray],
    sample_interval: int = 10,
) -> dict:
    """Analyse camera movement across a sequence of frames."""
    if len(frames) < 2:
        return {"pan": 0.0, "tilt": 0.0, "zoom": 0.0, "shake": 0.0}

    total_pan = 0.0
    shake_values = []

    for i in range(0, len(frames) - sample_interval, sample_interval):
        frame1 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        frame2 = cv2.cvtColor(
            frames[min(i + sample_interval, len(frames) - 1)], cv2.COLOR_BGR2GRAY,
        )

        rows, cols = frame1.shape
        block_size = 64

        if rows < block_size or cols < block_size:
            continue

        diffs = []
        for r in range(0, rows - block_size, block_size):
            for c in range(0, cols - block_size, block_size):
                block1 = frame1[r:r+block_size, c:c+block_size].astype(float)
                block2 = frame2[r:r+block_size, c:c+block_size].astype(float)
                diff = np.mean(np.abs(block1 - block2))
                diffs.append(diff)

        if diffs:
            avg_diff = np.mean(diffs)
            total_pan += avg_diff
            shake_values.append(avg_diff)

    n_samples = max(1, (len(frames) - sample_interval) // sample_interval)
    avg_pan = total_pan / n_samples

    return {
        "pan": avg_pan,
        "tilt": avg_pan * 0.5,
        "zoom": 0.0,
        "shake": float(np.std(shake_values)) if shake_values else 0.0,
    }


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

async def get_zoom_points(
    video_path: Path,
    video_duration: float,
    intensity_threshold: float = 0.4,
    min_spacing: float = 5.0,
) -> list[tuple[float, float]]:
    """
    Find optimal zoom points based on motion analysis.

    Returns list of (time, intensity) tuples for zoom effects.
    """
    detector = MotionDetector()
    analysis = await detector.analyze_video(video_path)

    zoom_points = []
    last_zoom_time = -min_spacing

    for frame in analysis.frames:
        if (
            frame.energy_level > intensity_threshold and
            frame.timestamp - last_zoom_time >= min_spacing
        ):
            intensity = min(1.0, frame.energy_level * 1.5)
            zoom_points.append((frame.timestamp, intensity))
            last_zoom_time = frame.timestamp

    logger.info("Found %d zoom points", len(zoom_points))
    return zoom_points


async def detect_scene_changes(
    video_path: Path,
    threshold: float = SCENE_CHANGE_THRESHOLD,
) -> list[float]:
    """
    Detect scene change timestamps in a video.

    Returns list of timestamps where scene changes occur.
    """
    detector = MotionDetector(scene_change_threshold=threshold)
    analysis = await detector.analyze_video(video_path)

    scene_times = [f.timestamp for f in analysis.frames if f.is_scene_change]
    logger.info("Detected %d scene changes", len(scene_times))
    return scene_times
