"""
Face Tracker — Detect and track the main speaker across video frames.

Uses OpenCV's Haar Cascade classifier for face detection with
Kalman filtering for smooth tracking. Falls back to center tracking
if no faces are detected.

Features:
- Haar Cascade face detection
- Multi-face detection with speaker selection
- Kalman filter smoothing for position interpolation
- Temporal consistency across frames
- Speaker identification (largest/most frequent face)
- Crop region calculation for auto-reframing
- Fallback to center if no faces
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from utilities.logging_config import get_logger

logger = get_logger("opencv_utils.face_tracker")

# Global cascade cache
_face_cascade: Optional[cv2.CascadeClassifier] = None


# ---------------------------------------------------------------------------
# Cascade Loading
# ---------------------------------------------------------------------------

def _get_face_cascade() -> Optional[cv2.CascadeClassifier]:
    """Load and return the Haar cascade classifier for face detection."""
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
        if _face_cascade.empty():
            logger.warning("Failed to load face cascade from: %s", cascade_path)
            return None
    return _face_cascade


# ---------------------------------------------------------------------------
# Single-Frame Detection
# ---------------------------------------------------------------------------

def detect_faces(
    frame: np.ndarray,
    min_size: tuple[int, int] = (50, 50),
    scale_factor: float = 1.1,
    min_neighbors: int = 5,
) -> list[tuple[int, int, int, int]]:
    """
    Detect faces in a single frame.

    Args:
        frame: BGR image (numpy array).
        min_size: Minimum face size (width, height).
        scale_factor: Image pyramid scale factor.
        min_neighbors: Minimum neighbors for a detection.

    Returns:
        List of face rectangles as (x, y, w, h) tuples.
    """
    cascade = _get_face_cascade()
    if cascade is None:
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=min_size,
    )

    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


# ---------------------------------------------------------------------------
# Speaker Tracking
# ---------------------------------------------------------------------------

def track_speaker(
    frame: np.ndarray,
    prev_face: Optional[tuple[int, int, int, int]] = None,
    search_radius: int = 100,
) -> tuple[int, int, int, int]:
    """
    Track the main speaker across frames.

    Uses the previous face position as a prior and searches
    within a radius for the best match.

    Args:
        frame: Current BGR frame.
        prev_face: Previous face rectangle (x, y, w, h).
        search_radius: Maximum search distance from previous position.

    Returns:
        Best face rectangle (x, y, w, h) or (0, 0, 0, 0) if no face found.
    """
    faces = detect_faces(frame)

    if not faces:
        if prev_face:
            return prev_face
        return (0, 0, 0, 0)

    if prev_face is None:
        return max(faces, key=lambda f: f[2] * f[3])

    # Find the face closest to the previous position
    prev_cx = prev_face[0] + prev_face[2] // 2
    prev_cy = prev_face[1] + prev_face[3] // 2

    best_face = None
    best_distance = float("inf")

    for face in faces:
        cx = face[0] + face[2] // 2
        cy = face[1] + face[3] // 2
        distance = np.sqrt((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2)

        if distance < search_radius and distance < best_distance:
            best_distance = distance
            best_face = face

    return best_face or faces[0]


def get_face_center(face: tuple[int, int, int, int]) -> tuple[int, int]:
    """Get the center point of a face rectangle."""
    x, y, w, h = face
    return (x + w // 2, y + h // 2)


# ---------------------------------------------------------------------------
# Crop Region Calculation
# ---------------------------------------------------------------------------

def calculate_crop_region(
    face: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    target_width: int,
    target_height: int,
    padding: float = 0.3,
) -> tuple[int, int, int, int]:
    """
    Calculate the crop region for auto-reframing.

    Centers the crop on the face with appropriate padding.

    Args:
        face: Face rectangle (x, y, w, h).
        frame_width: Source frame width.
        frame_height: Source frame height.
        target_width: Target crop width.
        target_height: Target crop height.
        padding: Extra padding around the face (0.0-1.0).

    Returns:
        Crop rectangle (x, y, w, h) clamped to frame bounds.
    """
    if face == (0, 0, 0, 0):
        cx = frame_width // 2
        cy = frame_height // 2
    else:
        cx, cy = get_face_center(face)

    crop_w = target_width
    crop_h = target_height

    x = cx - crop_w // 2
    y = cy - crop_h // 2

    x = max(0, min(x, frame_width - crop_w))
    y = max(0, min(y, frame_height - crop_h))

    return (int(x), int(y), crop_w, crop_h)


# ---------------------------------------------------------------------------
# Kalman Filter
# ---------------------------------------------------------------------------

class KalmanFilter2D:
    """
    Simple 2D Kalman filter for smoothing face positions.

    Tracks x, y coordinates with velocity estimation for
    smooth camera movement between detected positions.
    """

    def __init__(self, process_noise: float = 0.1, measurement_noise: float = 1.0):
        # State: [x, y, vx, vy]
        self.state = np.array([0.0, 0.0, 0.0, 0.0])
        self.F = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        self.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
        self.Q = np.eye(4) * process_noise
        self.R = np.eye(2) * measurement_noise
        self.P = np.eye(4) * 100
        self.initialized = False

    def predict(self) -> tuple[float, float]:
        """Predict next state."""
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.state[0]), float(self.state[1])

    def update(self, measurement: tuple[float, float]) -> tuple[float, float]:
        """Update state with new measurement."""
        z = np.array(measurement)

        if not self.initialized:
            self.state[0] = z[0]
            self.state[1] = z[1]
            self.initialized = True
            return float(z[0]), float(z[1])

        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        I = np.eye(4)
        self.P = (I - K @ self.H) @ self.P

        return float(self.state[0]), float(self.state[1])


# ---------------------------------------------------------------------------
# Full Video Face Tracking
# ---------------------------------------------------------------------------

class FaceTracker:
    """
    Detects and tracks faces across video frames.

    Uses OpenCV Haar Cascade for detection and Kalman filtering
    for smooth position tracking throughout the entire video.
    """

    def __init__(
        self,
        min_face_size: int = 50,
        max_face_size: int = 400,
        detection_interval: int = 10,
        smooth_factor: float = 0.3,
    ):
        self.min_face_size = min_face_size
        self.max_face_size = max_face_size
        self.detection_interval = detection_interval
        self.smooth_factor = smooth_factor

    async def track_faces(
        self,
        video_path: Path,
        sample_interval: int = 10,
        max_frames: Optional[int] = None,
    ) -> list[dict]:
        """
        Track faces throughout the video.

        Samples frames at regular intervals and detects faces,
        then returns smoothed position data.

        Args:
            video_path: Path to the video file.
            sample_interval: Sample every N seconds.
            max_frames: Maximum number of frames to process.

        Returns:
            List of face position dicts with keys: frame, x, y, width, height, weight.
        """
        cascade = _get_face_cascade()
        if cascade is None:
            logger.warning("No face cascade loaded, returning empty positions")
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Cannot open video: %s", video_path)
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frame_step = max(1, int(fps * sample_interval))
        if max_frames:
            frame_step = max(frame_step, total_frames // max_frames)

        logger.info(
            "Tracking faces: %dx%d, %.1f fps, %d frames, step=%d",
            width, height, fps, total_frames, frame_step,
        )

        kalman = KalmanFilter2D()
        positions = []
        frame_idx = 0
        processed = 0

        while True:
            target_frame = processed * frame_step
            if target_frame >= total_frames:
                break

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(self.min_face_size, self.min_face_size),
                maxSize=(self.max_face_size, self.max_face_size),
            )

            if len(faces) > 0:
                largest_face = max(faces, key=lambda f: f[2] * f[3])
                x, y, w, h = largest_face
                cx = x + w // 2
                cy = y + h // 2

                # Smooth with Kalman filter
                if frame_idx == 0:
                    kalman = KalmanFilter2D()
                    kalman.update((cx, cy))
                else:
                    kalman.predict()
                    kalman.update((cx, cy))

                smooth_x, smooth_y = kalman.state[0], kalman.state[1]

                positions.append({
                    "frame": frame_idx,
                    "x": int(smooth_x),
                    "y": int(smooth_y),
                    "width": w,
                    "height": h,
                    "weight": 1.0,
                })

            frame_idx += 1
            processed += 1

        cap.release()

        logger.info("Tracked %d face positions across %d frames", len(positions), frame_idx)
        return positions

    def get_primary_speaker_position(
        self,
        positions: list[dict],
        video_width: int,
        video_height: int,
    ) -> tuple[int, int]:
        """
        Determine the primary speaker position.

        Uses weighted average of all detected positions,
        favoring the most frequently detected face region.
        """
        if not positions:
            return video_width // 2, video_height // 3

        total_weight = 0
        weighted_x = 0
        weighted_y = 0

        for i, pos in enumerate(positions):
            weight = 1 + (i / max(len(positions), 1)) * 0.5
            weighted_x += pos["x"] * weight
            weighted_y += pos["y"] * weight
            total_weight += weight

        if total_weight > 0:
            return int(weighted_x / total_weight), int(weighted_y / total_weight)
        return video_width // 2, video_height // 3


# Module-level convenience

async def detect_faces_in_video(
    video_path: Path,
    sample_interval: int = 10,
) -> list[dict]:
    """Detect faces in a video (convenience function)."""
    tracker = FaceTracker()
    return await tracker.track_faces(video_path, sample_interval)
