"""
Common utilities shared across Telegram handlers.

Provides keyboard builders, message helpers, and formatting functions
used by all handler modules.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    User,
)
from telegram.ext import ContextTypes

from database import users as users_db
from database import settings as settings_db
from database import statistics as stats_db
from utilities.security import rate_limiter

logger = logging.getLogger(__name__)


# ===========================================================================
# Keyboard builders
# ===========================================================================

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu with navigation buttons."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Create Shorts", callback_data="menu_create")],
        [InlineKeyboardButton("⚙ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📂 History", callback_data="menu_history")],
        [InlineKeyboardButton("📈 Queue", callback_data="menu_queue")],
        [InlineKeyboardButton("❓ Help", callback_data="menu_help")],
        [InlineKeyboardButton("👤 Account", callback_data="menu_account")],
    ])


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the settings sub-menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔢 Number of Shorts", callback_data="setting_num_shorts"),
        ],
        [
            InlineKeyboardButton("✏ Caption Style", callback_data="setting_caption_style"),
            InlineKeyboardButton("🔤 Font", callback_data="setting_caption_font"),
        ],
        [
            InlineKeyboardButton("🎨 Caption Color", callback_data="setting_caption_color"),
        ],
        [
            InlineKeyboardButton("😀 Emoji: ON", callback_data="setting_emoji_on"),
            InlineKeyboardButton("😀 Emoji: OFF", callback_data="setting_emoji_off"),
        ],
        [
            InlineKeyboardButton("🔍 Zoom: ON", callback_data="setting_zoom_on"),
            InlineKeyboardButton("🔍 Zoom: OFF", callback_data="setting_zoom_off"),
        ],
        [
            InlineKeyboardButton("🎬 B-roll: ON", callback_data="setting_broll_on"),
            InlineKeyboardButton("🎬 B-roll: OFF", callback_data="setting_broll_off"),
        ],
        [
            InlineKeyboardButton("🔇 Silence Removal: ON", callback_data="setting_silence_on"),
            InlineKeyboardButton("🔇 Silence Removal: OFF", callback_data="setting_silence_off"),
        ],
        [
            InlineKeyboardButton("📊 Output Quality", callback_data="setting_output_quality"),
        ],
        [
            InlineKeyboardButton("🌐 Language", callback_data="setting_language"),
        ],
        [
            InlineKeyboardButton("🔥 Viral Detection Mode", callback_data="setting_viral_mode"),
        ],
        [
            InlineKeyboardButton("📤 Auto Upload: ON", callback_data="setting_autoupload_on"),
            InlineKeyboardButton("📤 Auto Upload: OFF", callback_data="setting_autoupload_off"),
        ],
        [
            InlineKeyboardButton("🗑 Delete Temp: ON", callback_data="setting_deletetemp_on"),
            InlineKeyboardButton("🗑 Delete Temp: OFF", callback_data="setting_deletetemp_off"),
        ],
        [InlineKeyboardButton("🔄 Reset to Defaults", callback_data="setting_reset")],
        [InlineKeyboardButton("◀ Back", callback_data="menu_back_main")],
    ])


def help_keyboard() -> InlineKeyboardMarkup:
    """Build the help menu keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 How It Works", callback_data="help_how_it_works"),
        ],
        [
            InlineKeyboardButton("📋 Commands", callback_data="help_commands"),
        ],
        [
            InlineKeyboardButton("⚠ Limits & Rules", callback_data="help_limits"),
        ],
        [
            InlineKeyboardButton("◀ Back", callback_data="menu_back_main"),
        ],
    ])


def account_keyboard() -> InlineKeyboardMarkup:
    """Build the account menu keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 My Stats", callback_data="account_stats"),
        ],
        [
            InlineKeyboardButton("📋 My Settings", callback_data="account_settings_view"),
        ],
        [
            InlineKeyboardButton("◀ Back", callback_data="menu_back_main"),
        ],
    ])


def queue_keyboard() -> InlineKeyboardMarkup:
    """Build the queue status keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="queue_refresh"),
        ],
        [
            InlineKeyboardButton("❌ Cancel My Jobs", callback_data="queue_cancel_my"),
        ],
        [
            InlineKeyboardButton("◀ Back", callback_data="menu_back_main"),
        ],
    ])


def caption_style_keyboard() -> InlineKeyboardMarkup:
    """Build the caption style selection keyboard."""
    styles = [
        ("hormozi", "🎤 Hormozi"),
        ("clean", "✨ Clean"),
        ("minimal", "📝 Minimal"),
        ("karaoke", "🎵 Karaoke"),
        ("typewriter", "⌨ Typewriter"),
    ]
    buttons = [
        [InlineKeyboardButton(text, callback_data=f"set_style_{style}")]
        for style, text in styles
    ]
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


def caption_font_keyboard() -> InlineKeyboardMarkup:
    """Build the caption font selection keyboard."""
    fonts = [
        ("montserrat", "Montserrat"),
        ("roboto", "Roboto"),
        ("oswald", "Oswald"),
        ("bebas", "Bebas Neue"),
        ("impact", "Impact"),
        ("arial", "Arial"),
    ]
    buttons = [
        [InlineKeyboardButton(text, callback_data=f"set_font_{font}")]
        for font, text in fonts
    ]
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


def caption_color_keyboard() -> InlineKeyboardMarkup:
    """Build the caption color selection keyboard."""
    colors = [
        ("#FFFFFF", "⬜ White"),
        ("#FFD700", "🟡 Gold"),
        ("#FF4444", "🔴 Red"),
        ("#44FF44", "🟢 Green"),
        ("#4488FF", "🔵 Blue"),
        ("#FF44FF", "🟣 Purple"),
        ("#FF8800", "🟠 Orange"),
        ("#00FFFF", "🩵 Cyan"),
    ]
    # Arrange in 2-column layout
    rows = []
    for i in range(0, len(colors), 2):
        row = []
        for _, (code, name) in enumerate(colors[i:i+2]):
            row.append(InlineKeyboardButton(name, callback_data=f"set_color_{code}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(rows)


def output_quality_keyboard() -> InlineKeyboardMarkup:
    """Build the output quality selection keyboard."""
    qualities = [
        ("low", "🔹 Low (720p)"),
        ("medium", "🔸 Medium (1080p)"),
        ("high", "🔶 High (1080p HQ)"),
        ("ultra", "⭐ Ultra (4K)"),
    ]
    buttons = [
        [InlineKeyboardButton(text, callback_data=f"set_quality_{q}")]
        for q, text in qualities
    ]
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


def language_keyboard() -> InlineKeyboardMarkup:
    """Build the language selection keyboard."""
    languages = [
        ("auto", "🌐 Auto Detect"),
        ("en", "🇬🇧 English"),
        ("es", "🇪🇸 Spanish"),
        ("fr", "🇫🇷 French"),
        ("de", "🇩🇪 German"),
        ("it", "🇮🇹 Italian"),
        ("pt", "🇧🇷 Portuguese"),
        ("ru", "🇷🇺 Russian"),
        ("ar", "🇸🇦 Arabic"),
        ("hi", "🇮🇳 Hindi"),
        ("ja", "🇯🇵 Japanese"),
        ("ko", "🇰🇷 Korean"),
        ("zh", "🇨🇳 Chinese"),
    ]
    buttons = []
    for i in range(0, len(languages), 2):
        row = [
            InlineKeyboardButton(text, callback_data=f"set_lang_{code}")
            for code, text in languages[i:i+2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


def viral_mode_keyboard() -> InlineKeyboardMarkup:
    """Build the viral detection mode selection keyboard."""
    modes = [
        ("top_3", "3️⃣ Top 3"),
        ("top_5", "5️⃣ Top 5"),
        ("top_10", "🔟 Top 10"),
        ("custom", "🎯 Custom"),
    ]
    buttons = [
        [InlineKeyboardButton(text, callback_data=f"set_viral_{mode}")]
        for mode, text in modes
    ]
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


# ===========================================================================
# Message helpers
# ===========================================================================

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the main menu to the user."""
    text = (
        "🎬 *Viral Shorts Bot*\n\n"
        "Welcome! Send me a YouTube URL or upload a video, "
        "and I'll turn it into viral short-form videos.\n\n"
        "Choose an option below:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )


async def send_settings_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: Optional[int] = None,
) -> None:
    """Send the settings menu, optionally showing current values."""
    if user_id is None and update.effective_user:
        user_id = update.effective_user.id

    # Fetch current settings for display
    settings = await settings_db.get_or_create_settings(user_id) if user_id else {}

    text = (
        "⚙ *Settings*\n\n"
        "🔢 Shorts: `{num}`\n"
        "✏ Style: `{style}`\n"
        "🔤 Font: `{font}`\n"
        "🎨 Color: `{color}`\n"
        "😀 Emoji: `{emoji}`\n"
        "🔍 Zoom: `{zoom}`\n"
        "🎬 B-roll: `{broll}`\n"
        "🔇 Silence: `{silence}`\n"
        "📊 Quality: `{quality}`\n"
        "🌐 Language: `{lang}`\n"
        "🔥 Viral: `{viral}`\n"
        "📤 Auto Upload: `{upload}`\n"
        "🗑 Delete Temp: `{temp}`\n"
    ).format(
        num=settings.get("num_shorts", 3),
        style=settings.get("caption_style", "hormozi"),
        font=settings.get("caption_font", "montserrat"),
        color=settings.get("caption_color", "#FFFFFF"),
        emoji="ON" if settings.get("emoji_enabled", 1) else "OFF",
        zoom="ON" if settings.get("zoom_enabled", 1) else "OFF",
        broll="ON" if settings.get("broll_enabled", 0) else "OFF",
        silence="ON" if settings.get("silence_removal", 1) else "OFF",
        quality=settings.get("output_quality", "high"),
        lang=settings.get("language", "auto"),
        viral=settings.get("viral_detection_mode", "top_3"),
        upload="ON" if settings.get("auto_upload", 1) else "OFF",
        temp="ON" if settings.get("delete_temp_files", 1) else "OFF",
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
        )


async def notify_user(user_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message to a user by ID."""
    try:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.debug("Failed to notify user %d: %s", user_id, e)


async def notify_user_with_keyboard(
    user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    context: ContextTypes.DEFAULT_TYPE,
    parse_mode: str = "Markdown",
) -> None:
    """Send a message with a keyboard to a user by ID."""
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.debug("Failed to notify user %d: %s", user_id, e)


# ===========================================================================
# Event logging helpers
# ===========================================================================

async def log_command(user_id: int, command: str) -> None:
    """Log a command usage event."""
    await stats_db.log_event(
        event_type="command_used",
        user_id=user_id,
        details={"command": command},
    )


async def log_setting_change(user_id: int, setting: str, value) -> None:
    """Log a settings change event."""
    await stats_db.log_event(
        event_type="setting_changed",
        user_id=user_id,
        details={"setting": setting, "value": str(value)},
    )
