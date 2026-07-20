"""
User settings database operations for the Viral Shorts Bot.

Provides CRUD operations for the ``user_settings`` table.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from configuration.config import DEFAULT_USER_SETTINGS
from database.connection import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_setting_key(key: str) -> bool:
    """Ensure the setting key exists in the default settings schema."""
    return key in DEFAULT_USER_SETTINGS


def _convert_bool(value) -> int:
    """Convert a Python bool / int to an SQLite integer (0/1)."""
    return 1 if value else 0


# ---------------------------------------------------------------------------
# Create / Upsert
# ---------------------------------------------------------------------------

async def get_or_create_settings(user_id: int) -> dict:
    """
    Return the user's settings, creating default settings if they don't exist.
    """
    conn = await get_connection()

    async with conn.execute(
        "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row is not None:
            return dict(row)

    # Create defaults
    defaults = DEFAULT_USER_SETTINGS.copy()
    defaults["user_id"] = user_id
    defaults["emoji_enabled"] = _convert_bool(defaults["emoji_enabled"])
    defaults["zoom_enabled"] = _convert_bool(defaults["zoom_enabled"])
    defaults["broll_enabled"] = _convert_bool(defaults["broll_enabled"])
    defaults["silence_removal"] = _convert_bool(defaults["silence_removal"])
    defaults["auto_upload"] = _convert_bool(defaults["auto_upload"])
    defaults["delete_temp_files"] = _convert_bool(defaults["delete_temp_files"])

    await conn.execute(
        """
        INSERT INTO user_settings (
            user_id, num_shorts, caption_style, caption_font, caption_color,
            caption_highlight_color, emoji_enabled, zoom_enabled, broll_enabled,
            silence_removal, output_quality, language, viral_detection_mode,
            auto_upload, delete_temp_files
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            defaults["user_id"],
            defaults["num_shorts"],
            defaults["caption_style"],
            defaults["caption_font"],
            defaults["caption_color"],
            defaults["caption_highlight_color"],
            defaults["emoji_enabled"],
            defaults["zoom_enabled"],
            defaults["broll_enabled"],
            defaults["silence_removal"],
            defaults["output_quality"],
            defaults["language"],
            defaults["viral_detection_mode"],
            defaults["auto_upload"],
            defaults["delete_temp_files"],
        ),
    )
    await conn.commit()

    logger.info("Created default settings for user %d", user_id)
    return defaults


async def reset_settings(user_id: int) -> dict:
    """Reset a user's settings to defaults. Returns the new settings."""
    conn = await get_connection()

    defaults = DEFAULT_USER_SETTINGS.copy()
    defaults["emoji_enabled"] = _convert_bool(defaults["emoji_enabled"])
    defaults["zoom_enabled"] = _convert_bool(defaults["zoom_enabled"])
    defaults["broll_enabled"] = _convert_bool(defaults["broll_enabled"])
    defaults["silence_removal"] = _convert_bool(defaults["silence_removal"])
    defaults["auto_upload"] = _convert_bool(defaults["auto_upload"])
    defaults["delete_temp_files"] = _convert_bool(defaults["delete_temp_files"])
    defaults["user_id"] = user_id

    await conn.execute(
        """
        INSERT INTO user_settings (
            user_id, num_shorts, caption_style, caption_font, caption_color,
            caption_highlight_color, emoji_enabled, zoom_enabled, broll_enabled,
            silence_removal, output_quality, language, viral_detection_mode,
            auto_upload, delete_temp_files
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            num_shorts = excluded.num_shorts,
            caption_style = excluded.caption_style,
            caption_font = excluded.caption_font,
            caption_color = excluded.caption_color,
            caption_highlight_color = excluded.caption_highlight_color,
            emoji_enabled = excluded.emoji_enabled,
            zoom_enabled = excluded.zoom_enabled,
            broll_enabled = excluded.broll_enabled,
            silence_removal = excluded.silence_removal,
            output_quality = excluded.output_quality,
            language = excluded.language,
            viral_detection_mode = excluded.viral_detection_mode,
            auto_upload = excluded.auto_upload,
            delete_temp_files = excluded.delete_temp_files,
            updated_at = datetime('now')
        """,
        (
            defaults["user_id"],
            defaults["num_shorts"],
            defaults["caption_style"],
            defaults["caption_font"],
            defaults["caption_color"],
            defaults["caption_highlight_color"],
            defaults["emoji_enabled"],
            defaults["zoom_enabled"],
            defaults["broll_enabled"],
            defaults["silence_removal"],
            defaults["output_quality"],
            defaults["language"],
            defaults["viral_detection_mode"],
            defaults["auto_upload"],
            defaults["delete_temp_files"],
        ),
    )
    await conn.commit()

    logger.info("Reset settings for user %d", user_id)
    return defaults


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_settings(user_id: int) -> dict:
    """Fetch a user's current settings (empty dict if none exist)."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else {}


async def get_settings_for_job(user_id: int) -> dict:
    """
    Return settings in a job-friendly format (with booleans, not ints).
    """
    raw = await get_or_create_settings(user_id)
    return {
        "num_shorts": raw.get("num_shorts", 3),
        "caption_style": raw.get("caption_style", "hormozi"),
        "caption_font": raw.get("caption_font", "montserrat"),
        "caption_color": raw.get("caption_color", "#FFFFFF"),
        "caption_highlight_color": raw.get("caption_highlight_color", "#FFD700"),
        "emoji_enabled": bool(raw.get("emoji_enabled", 1)),
        "zoom_enabled": bool(raw.get("zoom_enabled", 1)),
        "broll_enabled": bool(raw.get("broll_enabled", 0)),
        "silence_removal": bool(raw.get("silence_removal", 1)),
        "output_quality": raw.get("output_quality", "high"),
        "language": raw.get("language", "auto"),
        "viral_detection_mode": raw.get("viral_detection_mode", "top_3"),
        "auto_upload": bool(raw.get("auto_upload", 1)),
        "delete_temp_files": bool(raw.get("delete_temp_files", 1)),
    }


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_setting(user_id: int, key: str, value) -> dict:
    """
    Update a single setting for a user.

    Args:
        user_id: The Telegram user ID.
        key: The setting name (must be valid).
        value: The new value.

    Returns:
        The updated settings dictionary.
    """
    if not _validate_setting_key(key):
        raise ValueError(f"Invalid setting key: {key}")

    # Get existing or create defaults
    settings = await get_or_create_settings(user_id)

    # Convert booleans
    if key in ("emoji_enabled", "zoom_enabled", "broll_enabled", "silence_removal", "auto_upload", "delete_temp_files"):
        value = _convert_bool(value)

    conn = await get_connection()
    await conn.execute(
        f"UPDATE user_settings SET {key} = ?, updated_at = datetime('now') WHERE user_id = ?",
        (value, user_id),
    )
    await conn.commit()

    logger.info("Updated setting '%s' for user %d to %r", key, user_id, value)
    return await get_settings(user_id)


async def update_num_shorts(user_id: int, count: int) -> dict:
    """Set the number of shorts to generate."""
    if not 1 <= count <= 20:
        raise ValueError("num_shorts must be between 1 and 20")
    return await update_setting(user_id, "num_shorts", count)


async def update_caption_style(user_id: int, style: str) -> dict:
    """Set the caption style."""
    valid_styles = ("hormozi", "clean", "minimal", "karaoke", "typewriter")
    if style not in valid_styles:
        raise ValueError(f"Invalid caption style. Choose from: {', '.join(valid_styles)}")
    return await update_setting(user_id, "caption_style", style)


async def update_caption_font(user_id: int, font: str) -> dict:
    """Set the caption font."""
    return await update_setting(user_id, "caption_font", font)


async def update_caption_color(user_id: int, color: str) -> dict:
    """Set the caption color."""
    return await update_setting(user_id, "caption_color", color)


async def update_emoji_enabled(user_id: int, enabled: bool) -> dict:
    """Toggle emoji insertion."""
    return await update_setting(user_id, "emoji_enabled", enabled)


async def update_zoom_enabled(user_id: int, enabled: bool) -> dict:
    """Toggle dynamic zoom."""
    return await update_setting(user_id, "zoom_enabled", enabled)


async def update_broll_enabled(user_id: int, enabled: bool) -> dict:
    """Toggle B-roll insertion."""
    return await update_setting(user_id, "broll_enabled", enabled)


async def update_silence_removal(user_id: int, enabled: bool) -> dict:
    """Toggle silence removal."""
    return await update_setting(user_id, "silence_removal", enabled)


async def update_output_quality(user_id: int, quality: str) -> dict:
    """Set output quality."""
    valid = ("low", "medium", "high", "ultra")
    if quality not in valid:
        raise ValueError(f"Invalid quality. Choose from: {', '.join(valid)}")
    return await update_setting(user_id, "output_quality", quality)


async def update_language(user_id: int, language: str) -> dict:
    """Set the transcription language."""
    return await update_setting(user_id, "language", language)


async def update_viral_detection_mode(user_id: int, mode: str) -> dict:
    """Set the viral detection mode."""
    valid = ("top_3", "top_5", "top_10", "custom")
    if mode not in valid:
        raise ValueError(f"Invalid viral detection mode. Choose from: {', '.join(valid)}")
    return await update_setting(user_id, "viral_detection_mode", mode)


async def update_auto_upload(user_id: int, enabled: bool) -> dict:
    """Toggle auto-upload of finished shorts."""
    return await update_setting(user_id, "auto_upload", enabled)


async def update_delete_temp_files(user_id: int, enabled: bool) -> dict:
    """Toggle deletion of temporary files after processing."""
    return await update_setting(user_id, "delete_temp_files", enabled)
