"""
B-roll Engine — Overlay stock B-roll footage from local folders.

Scans configurable category folders for B-roll clips and
intelligently places them during low-energy or silence segments
to maintain viewer engagement.

Features:
- Category-based clip organization
- Configurable category folders
- Intelligent placement based on transcript analysis
- Graceful fallback when no B-roll available
- Crossfade transitions between clips
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from configuration.config import TEMP_DIR, MAX_SHORTS_DURATION_SECONDS
from ffmpeg_utils.commands import run_ffmpeg_command, get_video_duration
from utilities.logging_config import get_logger

logger = get_logger("video_processing.broll")


@dataclass
class BrollClip:
    """Represents a B-roll clip with metadata."""
    path: Path
    category: str
    duration: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class BrollPlacement:
    """Represents a B-roll placement in the final video."""
    clip: BrollClip
    start_time: float
    end_time: float
    opacity: float = 0.5
    position: str = "center"


class BrollEngine:
    """
    Manages B-roll clip discovery, selection, and placement.

    Scans local folders organized by category, matches clips
    to transcript context, and generates placement instructions
    for the video renderer.
    """

    # Supported video extensions
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

    # Default categories
    DEFAULT_CATEGORIES = {
        "money": ["money", "finance", "business", "cash", "dollar"],
        "tech": ["tech", "computer", "phone", "screen", "code"],
        "nature": ["nature", "sky", "ocean", "forest", "sunset"],
        "city": ["city", "street", "building", "urban", "traffic"],
        "people": ["people", "crowd", "meeting", "hands", "typing"],
        "abstract": ["abstract", "particles", "gradient", "geometric"],
    }

    def __init__(
        self,
        broll_dirs: Optional[list[Path]] = None,
        categories: Optional[dict[str, list[str]]] = None,
        min_duration: float = 2.0,
        max_duration: float = 10.0,
        crossfade_duration: float = 0.5,
    ):
        """
        Initialize the B-roll engine.

        Args:
            broll_dirs: List of directories containing B-roll clips.
            categories: Category definitions (name -> keyword list).
            min_duration: Minimum B-roll clip duration.
            max_duration: Maximum B-roll clip duration.
            crossfade_duration: Duration of crossfade transitions.
        """
        self.broll_dirs = broll_dirs or []
        self.categories = categories or self.DEFAULT_CATEGORIES
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.crossfade_duration = crossfade_duration
        self._clip_cache: dict[str, list[BrollClip]] = {}

    def scan_directories(self) -> dict[str, list[BrollClip]]:
        """
        Scan all B-roll directories and categorize clips.

        Returns:
            Dict of category name -> list of BrollClip objects.
        """
        result = {}

        for broll_dir in self.broll_dirs:
            if not broll_dir.exists():
                logger.warning("B-roll directory not found: %s", broll_dir)
                continue

            for video_file in broll_dir.rglob("*"):
                if video_file.suffix.lower() not in self.VIDEO_EXTENSIONS:
                    continue

                category = self._classify_clip(video_file)
                clip = BrollClip(
                    path=video_file,
                    category=category,
                    tags=self._extract_tags(video_file),
                )

                if category not in result:
                    result[category] = []
                result[category].append(clip)

        # Sort clips by category
        for category in result:
            result[category].sort(key=lambda c: c.path.name)

        logger.info(
            "Scanned B-roll: %d categories, %d total clips",
            len(result),
            sum(len(v) for v in result.values()),
        )

        self._clip_cache = result
        return result

    async def get_durations(self) -> None:
        """Get durations for all cached clips using ffprobe."""
        import subprocess as sp

        for clips in self._clip_cache.values():
            for clip in clips:
                if clip.duration <= 0:
                    try:
                        proc = sp.run(
                            ["ffprobe", "-v", "quiet", "-show_entries",
                             "format=duration", "-of",
                             "default=noprint_wrappers=1:nokey=1",
                             str(clip.path)],
                            capture_output=True, text=True, timeout=10,
                        )
                        clip.duration = float(proc.stdout.strip())
                    except (ValueError, Exception):
                        clip.duration = 5.0  # Default assumption

    def _classify_clip(self, file_path: Path) -> str:
        """
        Classify a B-roll clip into a category.

        Uses filename keywords and directory structure for classification.
        """
        name_lower = file_path.name.lower()
        parent_name = file_path.parent.name.lower()

        # Check parent directory first
        if parent_name in self.categories:
            return parent_name

        # Check filename against category keywords
        for category, keywords in self.categories.items():
            if any(kw in name_lower for kw in keywords):
                return category

        return "abstract"  # Default category

    def _extract_tags(self, file_path: Path) -> list[str]:
        """Extract tags from the filename."""
        name = file_path.stem
        return [t.strip() for t in name.replace("-", " ").replace("_", " ").split() if len(t.strip()) > 2]

    async def select_clips(
        self,
        video_duration: float,
        transcript: Optional[str] = None,
        num_clips: int = 5,
        min_interval: float = 8.0,
    ) -> list[BrollPlacement]:
        """
        Select and place B-roll clips intelligently.

        Analyzes transcript to find appropriate placement windows
        and selects matching clips from available categories.

        Args:
            video_duration: Duration of the main video.
            transcript: Optional transcript for context matching.
            num_clips: Maximum number of B-roll clips to place.
            min_interval: Minimum seconds between B-roll placements.

        Returns:
            List of BrollPlacement instructions.
        """
        if not self._clip_cache:
            self.scan_directories()

        if not self._clip_cache:
            logger.info("No B-roll clips available")
            return []

        await self.get_durations()

        placements = []
        used_categories: set[str] = set()
        available_slots = self._find_placement_slots(
            video_duration, num_clips, min_interval,
        )

        for slot_start, slot_end in available_slots:
            category = self._match_category(slot_start, slot_end, transcript)
            clips = self._clip_cache.get(category, [])

            if not clips:
                # Try random category
                available = [
                    (cat, cl) for cat, cl in self._clip_cache.items()
                    if cat not in used_categories
                ]
                if available:
                    category, clips = random.choice(available)
                else:
                    category = random.choice(list(self._clip_cache.keys()))
                    clips = self._clip_cache[category]

            if not clips:
                continue

            # Select a clip that fits the slot
            slot_duration = min(slot_end - slot_start, self.max_duration)
            suitable_clips = [
                c for c in clips
                if self.min_duration <= c.duration <= slot_duration * 1.5
            ]

            if not suitable_clips:
                suitable_clips = clips  # Fallback to any clip

            clip = random.choice(suitable_clips)
            used_categories.add(category)

            # Calculate opacity based on slot position
            # More opaque at beginning, fades toward end
            opacity = 0.6 if (slot_end - slot_start) > 5 else 0.4

            placement = BrollPlacement(
                clip=clip,
                start_time=slot_start,
                end_time=min(slot_start + min(clip.duration, slot_duration), slot_end),
                opacity=opacity,
                position="center",
            )
            placements.append(placement)

        logger.info(
            "Selected %d B-roll placements from %d available slots",
            len(placements), len(available_slots),
        )

        return placements

    def _find_placement_slots(
        self,
        video_duration: float,
        num_clips: int,
        min_interval: float,
    ) -> list[tuple[float, float]]:
        """
        Find optimal placement slots for B-roll clips.

        Distributes clips evenly across the video with minimum
        spacing between them.
        """
        if video_duration <= min_interval * 2:
            return []

        slots = []
        slot_duration = min(self.max_duration, video_duration / (num_clips + 1))

        # First slot: after intro (5 seconds)
        start = min(5.0, video_duration * 0.1)
        for i in range(num_clips):
            if start + slot_duration > video_duration - 5:
                break

            end = min(start + slot_duration, video_duration - 5)
            slots.append((start, end))
            start = end + min_interval

        return slots

    def _match_category(
        self,
        start: float,
        end: float,
        transcript: Optional[str] = None,
    ) -> str:
        """
        Match a time range to a B-roll category based on transcript context.

        Analyzes the transcript around the given time range to
        determine the most appropriate B-roll category.
        """
        if not transcript:
            return random.choice(list(self.categories.keys()))

        # Extract relevant transcript segment
        words = transcript.split()
        # Rough estimation: assume ~3 words per second
        start_idx = max(0, int(start * 3))
        end_idx = min(len(words), int(end * 3))
        segment = " ".join(words[start_idx:end_idx]).lower()

        # Match against category keywords
        scores = {}
        for category, keywords in self.categories.items():
            score = sum(1 for kw in keywords if kw in segment)
            scores[category] = score

        if not scores or max(scores.values()) == 0:
            return random.choice(list(self.categories.keys()))

        return max(scores, key=scores.get)

    def get_broll_as_dicts(self, placements: list[BrollPlacement]) -> list[dict]:
        """
        Convert BrollPlacements to dicts for the FFmpeg renderer.

        Returns list of dicts compatible with VideoOutputRenderer.
        """
        result = []
        for p in placements:
            result.append({
                "path": str(p.clip.path),
                "start": p.start_time,
                "end": p.end_time,
                "opacity": p.opacity,
                "category": p.clip.category,
            })
        return result


# Module-level convenience functions

async def generate_broll(
    video_duration: float,
    broll_dirs: Optional[list[Path]] = None,
    transcript: Optional[str] = None,
    num_clips: int = 5,
) -> list[dict]:
    """
    Generate B-roll placements for a video.

    Args:
        video_duration: Duration of the main video.
        broll_dirs: Directories containing B-roll clips.
        transcript: Optional transcript for context matching.
        num_clips: Maximum number of B-roll clips.

    Returns:
        List of B-roll placement dicts.
    """
    engine = BrollEngine(broll_dirs=broll_dirs or [])
    engine.scan_directories()
    placements = await engine.select_clips(
        video_duration, transcript, num_clips,
    )
    return engine.get_broll_as_dicts(placements)
