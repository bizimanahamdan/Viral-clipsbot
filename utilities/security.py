"""
Security module for the Viral Shorts Bot.

Provides rate limiting, file validation, size enforcement,
and input sanitisation utilities.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import validators
from telegram import Message, User

from configuration.config import (
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_DOWNLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    RATE_LIMIT_PER_MINUTE,
    RATE_LIMIT_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# Rate Limiting
# ===========================================================================

class RateLimiter:
    """
    Sliding-window rate limiter per user.

    Tracks the number of actions each user has performed within the
    configured window and blocks further actions when the limit is exceeded.
    """

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_PER_MINUTE,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # user_id -> list of timestamps
        self._timestamps: dict[int, list[float]] = defaultdict(list)

    def _cleanup(self, user_id: int) -> None:
        """Remove timestamps outside the current window."""
        cutoff = time.monotonic() - self._window_seconds
        self._timestamps[user_id] = [
            ts for ts in self._timestamps[user_id] if ts > cutoff
        ]

    def is_rate_limited(self, user_id: int) -> bool:
        """Return True if the user has exceeded the rate limit."""
        self._cleanup(user_id)
        return len(self._timestamps[user_id]) >= self._max_requests

    def register_request(self, user_id: int) -> None:
        """Record a new request for the user."""
        self._timestamps[user_id].append(time.monotonic())

    def get_remaining(self, user_id: int) -> int:
        """Return the number of remaining requests in the current window."""
        self._cleanup(user_id)
        return max(0, self._max_requests - len(self._timestamps[user_id]))

    def get_reset_seconds(self, user_id: int) -> float:
        """Return seconds until the rate limit window resets."""
        self._cleanup(user_id)
        if not self._timestamps[user_id]:
            return 0.0
        oldest = self._timestamps[user_id][0]
        elapsed = time.monotonic() - oldest
        return max(0.0, self._window_seconds - elapsed)


# Global rate limiter instance
rate_limiter = RateLimiter()


# ===========================================================================
# File Validation
# ===========================================================================

def validate_file_extension(filename: str) -> bool:
    """
    Check whether the file extension is in the allowed list.

    Args:
        filename: The original filename from Telegram.

    Returns:
        True if the extension is allowed.
    """
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext in ALLOWED_VIDEO_EXTENSIONS


def validate_file_size(file_size: int, is_upload: bool = True) -> tuple[bool, str]:
    """
    Validate a file's size against the configured limits.

    Args:
        file_size: Size in bytes.
        is_upload: If True, check MAX_UPLOAD_SIZE_BYTES; otherwise MAX_DOWNLOAD_SIZE_BYTES.

    Returns:
        (is_valid, reason) tuple.
    """
    max_size = MAX_UPLOAD_SIZE_BYTES if is_upload else MAX_DOWNLOAD_SIZE_BYTES
    if file_size <= 0:
        return False, "File size must be greater than zero."
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f"File too large ({file_size / (1024*1024):.1f} MB). Maximum is {max_mb:.0f} MB."
    return True, ""


def validate_uploaded_video(message: Message) -> tuple[bool, str]:
    """
    Comprehensive validation of an uploaded video document.

    Checks:
    - File extension
    - File size

    Returns:
        (is_valid, error_message) tuple.
    """
    # Extract file info from the message
    doc = message.document
    video = message.video

    if doc is None and video is None:
        return False, "No document or video found in the message."

    # Determine file info
    if doc:
        file_id = doc.file_id
        file_name = doc.file_name or "video.mp4"
        file_size = doc.file_size or 0
    else:  # video
        file_id = video.file_id
        file_name = f"video_{video.file_unique_id}.mp4"
        file_size = video.file_size or 0

    # Validate extension
    if not validate_file_extension(file_name):
        return False, (
            f"Unsupported file type: .{Path(file_name).suffix.lstrip('.')}.\n"
            f"Allowed types: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        )

    # Validate size
    is_valid, reason = validate_file_size(file_size, is_upload=True)
    if not is_valid:
        return False, reason

    return True, ""


def validate_youtube_url(url: str) -> tuple[bool, str]:
    """
    Validate a YouTube (or YouTube-like) URL.

    Supports:
    - youtube.com/watch?v=...
    - youtu.be/...
    - youtube.com/shorts/...

    Returns:
        (is_valid, reason) tuple.
    """
    url = url.strip()

    # Basic URL check
    if not validators.url(url):
        return False, "This does not appear to be a valid URL."

    # Check for YouTube-specific patterns
    youtube_patterns = [
        r"youtube\.com/watch\?v=",
        r"youtu\.be/",
        r"youtube\.com/shorts/",
        r"youtube\.com/live/",
        r"youtube\.com/playlist\?list=",
    ]

    for pattern in youtube_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            # Reject playlists
            if "playlist" in pattern and "list=" in url:
                return False, "Playlists are not supported. Please provide a single video URL."
            return True, ""

    return False, (
        "This URL is not a supported YouTube link.\n"
        "Please provide a link to a single YouTube video (not a playlist)."
    )


# ===========================================================================
# Input Sanitisation
# ===========================================================================

def sanitise_filename(filename: str) -> str:
    """
    Sanitise a filename to prevent directory traversal and invalid characters.

    Strips path separators, control characters, and excessively long names.
    """
    # Remove path separators
    filename = re.sub(r'[\\/]', '', filename)

    # Remove control characters (0x00-0x1F and 0x7F)
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)

    # Remove leading/trailing whitespace and dots
    filename = filename.strip('. \t\n\r')

    # Truncate to 200 characters (preserve extension)
    if len(filename) > 200:
        ext = Path(filename).suffix
        filename = filename[:200 - len(ext)] + ext

    # Fallback if the filename becomes empty
    if not filename:
        filename = "untitled_video.mp4"

    return filename


def sanitise_text(text: str, max_length: int = 1000) -> str:
    """
    Sanitise free-form text input (e.g. captions, custom prompts).

    Removes control characters and truncates to max_length.
    """
    text = re.sub(r'[\x00-\x1f\x7f]', '', text)
    text = text.strip()
    return text[:max_length]


# ===========================================================================
# Hashing utilities
# ===========================================================================

def file_hash(filepath: Path | str) -> str:
    """
    Compute a SHA-256 hash of a file for deduplication and caching.
    """
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def url_hash(url: str) -> str:
    """Compute a SHA-256 hash of a URL string."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


# ===========================================================================
# Admin checks
# ===========================================================================

def check_admin(user: User) -> bool:
    """
    Verify that a user is an admin.

    Returns:
        True if the user is in the admin list.
    """
    from configuration.config import is_admin
    return is_admin(user.id)


def require_admin(user: User) -> tuple[bool, str]:
    """
    Check admin status and return an error message if not admin.

    Returns:
        (is_admin, message)
    """
    if check_admin(user):
        return True, ""
    return False, "You do not have permission to use this command."
