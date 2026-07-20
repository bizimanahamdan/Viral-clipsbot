"""
Configuration module for the Viral Shorts Bot.

Loads all settings from .env file and provides typed access to configuration
values throughout the application.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env file at module level so config is available on import
load_dotenv()

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------

# Project root directory
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Directories
UPLOADS_DIR: Path = PROJECT_ROOT / "uploads"
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"
CACHE_DIR: Path = PROJECT_ROOT / "cache"
TEMP_DIR: Path = PROJECT_ROOT / "temp"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATABASE_PATH: Path = PROJECT_ROOT / "database" / "viral_shorts.db"

# Ensure directories exist
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_IDS: list[int] = [
    int(uid) for uid in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if uid.strip()
]
TELEGRAM_SESSION_STRING: str = os.getenv("TELEGRAM_SESSION_STRING", "")

# Bot behaviour
TELEGRAM_POLLING_INTERVAL: int = int(os.getenv("TELEGRAM_POLLING_INTERVAL", "0"))
TELEGRAM_ALLOWED_UPDATES: list[str] = [
    "message",
    "callback_query",
    "edited_message",
    "channel_post",
    "chat_member",
]


# ---------------------------------------------------------------------------
# Groq API
# ---------------------------------------------------------------------------

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_WHISPER_MODEL: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL: str = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


# ---------------------------------------------------------------------------
# Video Processing
# ---------------------------------------------------------------------------

# FFmpeg
FFMPEG_THREADS: int = int(os.getenv("FFMPEG_THREADS", "4"))
FFMPEG_HWACCEL: str = os.getenv("FFMPEG_HWACCEL", "auto")
FFMPEG_PRESET: str = os.getenv("FFMPEG_PRESET", "medium")
FFMPEG_MAX_DURATION_SECONDS: int = int(os.getenv("FFMPEG_MAX_DURATION_SECONDS", "3600"))

# Output settings
OUTPUT_WIDTH: int = int(os.getenv("OUTPUT_WIDTH", "1080"))
OUTPUT_HEIGHT: int = int(os.getenv("OUTPUT_HEIGHT", "1920"))
OUTPUT_FPS: int = int(os.getenv("OUTPUT_FPS", "30"))
OUTPUT_VIDEO_CODEC: str = os.getenv("OUTPUT_VIDEO_CODEC", "libx264")
OUTPUT_AUDIO_CODEC: str = os.getenv("OUTPUT_AUDIO_CODEC", "aac")
OUTPUT_VIDEO_BITRATE: str = os.getenv("OUTPUT_VIDEO_BITRATE", "8M")
OUTPUT_AUDIO_BITRATE: str = os.getenv("OUTPUT_AUDIO_BITRATE", "192k")
OUTPUT_PIXEL_FORMAT: str = os.getenv("OUTPUT_PIXEL_FORMAT", "yuv420p")

# Short clip settings
MAX_SHORTS_DURATION_SECONDS: int = int(os.getenv("MAX_SHORTS_DURATION_SECONDS", "60"))
MIN_SHORTS_DURATION_SECONDS: int = int(os.getenv("MIN_SHORTS_DURATION_SECONDS", "15"))
MAX_SHORTS_COUNT: int = int(os.getenv("MAX_SHORTS_COUNT", "10"))
MAX_SHORTS_PER_REQUEST: int = int(os.getenv("MAX_SHORTS_PER_REQUEST", "5"))

# Audio extraction
AUDIO_CHUNK_SIZE_SECONDS: int = int(os.getenv("AUDIO_CHUNK_SIZE_SECONDS", "300"))
AUDIO_SAMPLE_RATE: int = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS: int = int(os.getenv("AUDIO_CHANNELS", "1"))

# Transcription
TRANSCRIPTION_TIMEOUT: int = int(os.getenv("TRANSCRIPTION_TIMEOUT", "600"))

# YouTube
MAX_YOUTUBE_DURATION_SECONDS: int = int(os.getenv("MAX_YOUTUBE_DURATION_SECONDS", "7200"))

# Output
SHORTS_WIDTH: int = int(os.getenv("SHORTS_WIDTH", "1080"))
SHORTS_HEIGHT: int = int(os.getenv("SHORTS_HEIGHT", "1920"))

# B-roll
BROLL_DIRS: list[str] = [d.strip() for d in os.getenv("BROLL_DIRS", "").split(",") if d.strip()]


# ---------------------------------------------------------------------------
# Queue System
# ---------------------------------------------------------------------------

QUEUE_MAX_CONCURRENT_JOBS: int = int(os.getenv("QUEUE_MAX_CONCURRENT_JOBS", "2"))
QUEUE_MAX_RETRIES: int = int(os.getenv("QUEUE_MAX_RETRIES", "3"))
QUEUE_RETRY_DELAY_SECONDS: int = int(os.getenv("QUEUE_RETRY_DELAY_SECONDS", "10"))
QUEUE_JOB_TIMEOUT_SECONDS: int = int(os.getenv("QUEUE_JOB_TIMEOUT_SECONDS", "1800"))


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(2 * 1024 * 1024 * 1024)))  # 2 GB
MAX_DOWNLOAD_SIZE_BYTES: int = int(os.getenv("MAX_DOWNLOAD_SIZE_BYTES", str(4 * 1024 * 1024 * 1024)))  # 4 GB
RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
ALLOWED_VIDEO_EXTENSIONS: set[str] = {"mp4", "mkv", "mov", "avi", "webm", "flv", "wmv"}


# ---------------------------------------------------------------------------
# Caption Defaults
# ---------------------------------------------------------------------------

CAPTION_FONT_PATH: Path = PROJECT_ROOT / "fonts" / "Montserrat-Bold.ttf"
CAPTION_STYLE: str = os.getenv("CAPTION_STYLE", "hormozi")
CAPTION_COLOR: str = os.getenv("CAPTION_COLOR", "#FFFFFF")
CAPTION_HIGHLIGHT_COLOR: str = os.getenv("CAPTION_HIGHLIGHT_COLOR", "#FFD700")
CAPTION_FONT_SIZE: int = int(os.getenv("CAPTION_FONT_SIZE", "48"))
CAPTION_STROKE_COLOR: str = os.getenv("CAPTION_STROKE_COLOR", "#000000")
CAPTION_STROKE_WIDTH: int = int(os.getenv("CAPTION_STROKE_WIDTH", "2"))


# ---------------------------------------------------------------------------
# Default User Settings (stored in DB per user)
# ---------------------------------------------------------------------------

DEFAULT_USER_SETTINGS: dict = {
    "num_shorts": 3,
    "caption_style": "hormozi",
    "caption_font": "montserrat",
    "caption_color": "#FFFFFF",
    "caption_highlight_color": "#FFD700",
    "emoji_enabled": True,
    "zoom_enabled": True,
    "broll_enabled": False,
    "silence_removal": True,
    "output_quality": "high",
    "language": "auto",
    "viral_detection_mode": "top_3",
    "auto_upload": True,
    "delete_temp_files": True,
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    """Check if a user ID is in the admin list."""
    return user_id in TELEGRAM_ADMIN_IDS


def get_user_settings_dict() -> dict:
    """Return a copy of the default user settings."""
    return DEFAULT_USER_SETTINGS.copy()


# Backwards-compatible aliases
MAX_VIDEO_DURATION_MIN: int = MAX_YOUTUBE_DURATION_SECONDS // 60
MAX_VIDEO_SIZE_MB: int = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)


def validate_config() -> list[str]:
    """
    Validate the loaded configuration and return a list of issues.
    An empty list means the configuration is valid.
    """
    issues: list[str] = []

    if not TELEGRAM_BOT_TOKEN:
        issues.append("TELEGRAM_BOT_TOKEN is not set in .env")

    if not GROQ_API_KEY:
        issues.append("GROQ_API_KEY is not set in .env")

    if not TELEGRAM_ADMIN_IDS:
        issues.append("TELEGRAM_ADMIN_IDS is not set in .env")

    if FFMPEG_THREADS < 1:
        issues.append("FFMPEG_THREADS must be >= 1")

    if MAX_UPLOAD_SIZE_BYTES < 0:
        issues.append("MAX_UPLOAD_SIZE_BYTES must be non-negative")

    return issues
