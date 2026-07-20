"""
Callback query handlers for the Viral Shorts Bot.

Handles all inline button presses from keyboards, including:
- Main menu navigation
- Settings adjustments
- Help sub-pages
- Account info
- Queue management
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from database import users as users_db
from database import settings as settings_db
from database import history as history_db
from database import jobs as jobs_db
from database import statistics as stats_db
from telegram_handlers.common import (
    main_menu_keyboard,
    settings_menu_keyboard,
    help_keyboard,
    account_keyboard,
    queue_keyboard,
    caption_style_keyboard,
    caption_font_keyboard,
    caption_color_keyboard,
    output_quality_keyboard,
    language_keyboard,
    viral_mode_keyboard,
    send_main_menu,
    send_settings_menu,
    log_setting_change,
    notify_user,
)
from utilities.queue_manager import queue_manager

logger = logging.getLogger(__name__)


# ===========================================================================
# Callback dispatcher
# ===========================================================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main callback query dispatcher.

    Routes the callback_data to the appropriate handler function.
    """
    query = update.callback_query
    if not query:
        return

    data = query.data
    user = update.effective_user
    if not user:
        return

    # Acknowledge the callback to prevent the "loading" spinner
    await query.answer()

    # Route based on callback data prefix
    if data == "menu_back_main":
        await _handle_back_to_main(update, context, user.id)
    elif data == "menu_create":
        await _handle_create_shorts(update, context, user.id)
    elif data == "menu_settings":
        await _handle_settings_menu(update, context, user.id)
    elif data == "menu_history":
        await _handle_history_menu(update, context, user.id)
    elif data == "menu_queue":
        await _handle_queue_menu(update, context, user.id)
    elif data == "menu_help":
        await _handle_help_menu(update, context, user.id)
    elif data == "menu_account":
        await _handle_account_menu(update, context, user.id)

    # Settings callbacks
    elif data == "setting_num_shorts":
        await _handle_setting_num_shorts(update, context, user.id)
    elif data == "setting_caption_style":
        await _handle_setting_caption_style(update, context, user.id)
    elif data == "setting_caption_font":
        await _handle_setting_caption_font(update, context, user.id)
    elif data == "setting_caption_color":
        await _handle_setting_caption_color(update, context, user.id)
    elif data == "setting_emoji_on":
        await _handle_toggle_emoji(update, context, user.id, True)
    elif data == "setting_emoji_off":
        await _handle_toggle_emoji(update, context, user.id, False)
    elif data == "setting_zoom_on":
        await _handle_toggle_zoom(update, context, user.id, True)
    elif data == "setting_zoom_off":
        await _handle_toggle_zoom(update, context, user.id, False)
    elif data == "setting_broll_on":
        await _handle_toggle_broll(update, context, user.id, True)
    elif data == "setting_broll_off":
        await _handle_toggle_broll(update, context, user.id, False)
    elif data == "setting_silence_on":
        await _handle_toggle_silence(update, context, user.id, True)
    elif data == "setting_silence_off":
        await _handle_toggle_silence(update, context, user.id, False)
    elif data == "setting_output_quality":
        await _handle_setting_output_quality(update, context, user.id)
    elif data == "setting_language":
        await _handle_setting_language(update, context, user.id)
    elif data == "setting_viral_mode":
        await _handle_setting_viral_mode(update, context, user.id)
    elif data == "setting_autoupload_on":
        await _handle_toggle_autoupload(update, context, user.id, True)
    elif data == "setting_autoupload_off":
        await _handle_toggle_autoupload(update, context, user.id, False)
    elif data == "setting_deletetemp_on":
        await _handle_toggle_deletetemp(update, context, user.id, True)
    elif data == "setting_deletetemp_off":
        await _handle_toggle_deletetemp(update, context, user.id, False)
    elif data == "setting_reset":
        await _handle_reset_settings(update, context, user.id)

    # Setting value callbacks (set_style_*, set_font_*, etc.)
    elif data.startswith("set_style_"):
        await _handle_set_style(update, context, user.id, data.replace("set_style_", ""))
    elif data.startswith("set_font_"):
        await _handle_set_font(update, context, user.id, data.replace("set_font_", ""))
    elif data.startswith("set_color_"):
        await _handle_set_color(update, context, user.id, data.replace("set_color_", ""))
    elif data.startswith("set_quality_"):
        await _handle_set_quality(update, context, user.id, data.replace("set_quality_", ""))
    elif data.startswith("set_lang_"):
        await _handle_set_language(update, context, user.id, data.replace("set_lang_", ""))
    elif data.startswith("set_viral_"):
        await _handle_set_viral_mode(update, context, user.id, data.replace("set_viral_", ""))

    # Help sub-pages
    elif data == "help_how_it_works":
        await _handle_help_how_it_works(update, context)
    elif data == "help_commands":
        await _handle_help_commands(update, context)
    elif data == "help_limits":
        await _handle_help_limits(update, context)

    # Account sub-pages
    elif data == "account_stats":
        await _handle_account_stats(update, context, user.id)
    elif data == "account_settings_view":
        await _handle_account_settings_view(update, context, user.id)

    # Queue management
    elif data == "queue_refresh":
        await _handle_queue_refresh(update, context, user.id)
    elif data == "queue_cancel_my":
        await _handle_queue_cancel_my(update, context, user.id)


# ===========================================================================
# Menu navigation handlers
# ===========================================================================

async def _handle_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Return to the main menu."""
    await send_main_menu(update, context)


async def _handle_create_shorts(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle 'Create Shorts' button — prompt for video input."""
    text = (
        "🎬 *Create Viral Shorts*\n\n"
        "Send me:\n"
        "• A *YouTube URL* (e.g. https://youtube.com/watch?v=...)\n"
        "• An *MP4 file* (upload directly)\n\n"
        "I'll process it and create viral Shorts for you!\n\n"
        "⚙ Your current settings will be used. "
        "Change them in /settings if needed."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Settings button."""
    await send_settings_menu(update, context, user_id)


async def _handle_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle History button."""
    history = await history_db.get_user_history(user_id, limit=10)

    if not history:
        text = (
            "📂 *History*\n\n"
            "You haven't generated any Shorts yet.\n"
            "Send me a YouTube URL or upload a video!"
        )
        await update.callback_query.edit_message_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
        return

    text = "📂 *Your Recent Shorts*\n\n"
    for i, record in enumerate(history[:10], 1):
        title = record.get("title") or "Untitled"
        duration = record.get("duration_seconds", 0) or 0
        text += f"*{i}.* {title} ({duration:.0f}s)\n"

    total = await history_db.get_user_history_count(user_id)
    text += f"\nTotal: {total} Shorts"

    await update.callback_query.edit_message_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_queue_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Queue button."""
    active_jobs = await jobs_db.get_user_active_jobs(user_id)

    if not active_jobs:
        text = (
            "📈 *Queue*\n\n"
            "No active jobs.\n"
            "Your queue is empty."
        )
    else:
        text = "📈 *Active Jobs*\n\n"
        for job in active_jobs:
            status = job["status"].title()
            progress = job.get("progress", 0)
            msg = job.get("progress_message", "")
            text += f"• {status} ({progress}%) — {msg}\n"

    await update.callback_query.edit_message_text(
        text, reply_markup=queue_keyboard(), parse_mode="Markdown"
    )


async def _handle_help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Help button."""
    text = (
        "❓ *Help*\n\n"
        "Choose a topic below for detailed information."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=help_keyboard(), parse_mode="Markdown"
    )


async def _handle_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Account button."""
    text = (
        "👤 *Account*\n\n"
        "View your stats and settings below."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=account_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Settings handlers
# ===========================================================================

async def _handle_setting_num_shorts(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Number of Shorts setting."""
    text = (
        "🔢 *Number of Shorts*\n\n"
        "Send a number between *1* and *20*.\n"
        "This determines how many Shorts will be generated from your video.\n\n"
        "Current: Use /settings to view current value."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )
    # Store state for the next message handler to pick up
    context.user_data["pending_setting"] = "num_shorts"


async def _handle_setting_caption_style(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Caption Style setting."""
    text = "✏ *Caption Style*\n\nChoose your preferred style:"
    await update.callback_query.edit_message_text(
        text, reply_markup=caption_style_keyboard(), parse_mode="Markdown"
    )


async def _handle_setting_caption_font(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Caption Font setting."""
    text = "🔤 *Caption Font*\n\nChoose your preferred font:"
    await update.callback_query.edit_message_text(
        text, reply_markup=caption_font_keyboard(), parse_mode="Markdown"
    )


async def _handle_setting_caption_color(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Caption Color setting."""
    text = "🎨 *Caption Color*\n\nChoose your preferred caption color:"
    await update.callback_query.edit_message_text(
        text, reply_markup=caption_color_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle Emoji toggle."""
    await settings_db.update_emoji_enabled(user_id, enabled)
    await log_setting_change(user_id, "emoji_enabled", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"😀 Emoji has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_zoom(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle Zoom toggle."""
    await settings_db.update_zoom_enabled(user_id, enabled)
    await log_setting_change(user_id, "zoom_enabled", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"🔍 Dynamic Zoom has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_broll(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle B-roll toggle."""
    await settings_db.update_broll_enabled(user_id, enabled)
    await log_setting_change(user_id, "broll_enabled", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"🎬 B-roll has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_silence(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle Silence Removal toggle."""
    await settings_db.update_silence_removal(user_id, enabled)
    await log_setting_change(user_id, "silence_removal", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"🔇 Silence Removal has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_setting_output_quality(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Output Quality setting."""
    text = "📊 *Output Quality*\n\nChoose your preferred quality:"
    await update.callback_query.edit_message_text(
        text, reply_markup=output_quality_keyboard(), parse_mode="Markdown"
    )


async def _handle_setting_language(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Language setting."""
    text = "🌐 *Language*\n\nChoose the transcription language:"
    await update.callback_query.edit_message_text(
        text, reply_markup=language_keyboard(), parse_mode="Markdown"
    )


async def _handle_setting_viral_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Viral Detection Mode setting."""
    text = "🔥 *Viral Detection Mode*\n\nChoose how many viral moments to detect:"
    await update.callback_query.edit_message_text(
        text, reply_markup=viral_mode_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_autoupload(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle Auto Upload toggle."""
    await settings_db.update_auto_upload(user_id, enabled)
    await log_setting_change(user_id, "auto_upload", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"📤 Auto Upload has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_toggle_deletetemp(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> None:
    """Handle Delete Temp Files toggle."""
    await settings_db.update_delete_temp_files(user_id, enabled)
    await log_setting_change(user_id, "delete_temp_files", enabled)

    status = "enabled" if enabled else "disabled"
    text = f"🗑 Delete Temp Files has been *{status}*."

    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_reset_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Reset to Defaults."""
    await settings_db.reset_settings(user_id)
    await log_setting_change(user_id, "reset", True)

    text = (
        "🔄 *Settings Reset*\n\n"
        "All settings have been reset to their default values."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Setting value handlers
# ===========================================================================

async def _handle_set_style(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, style: str) -> None:
    """Handle caption style selection."""
    await settings_db.update_caption_style(user_id, style)
    await log_setting_change(user_id, "caption_style", style)

    text = f"✏ Caption style set to *{style}*."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_set_font(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, font: str) -> None:
    """Handle caption font selection."""
    await settings_db.update_caption_font(user_id, font)
    await log_setting_change(user_id, "caption_font", font)

    text = f"🔤 Caption font set to *{font}*."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_set_color(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, color: str) -> None:
    """Handle caption color selection."""
    await settings_db.update_caption_color(user_id, color)
    await log_setting_change(user_id, "caption_color", color)

    text = f"🎨 Caption color set to `{color}`."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_set_quality(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, quality: str) -> None:
    """Handle output quality selection."""
    await settings_db.update_output_quality(user_id, quality)
    await log_setting_change(user_id, "output_quality", quality)

    text = f"📊 Output quality set to *{quality}*."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_set_language(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, lang: str) -> None:
    """Handle language selection."""
    await settings_db.update_language(user_id, lang)
    await log_setting_change(user_id, "language", lang)

    text = f"🌐 Language set to *{lang}*."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


async def _handle_set_viral_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, mode: str) -> None:
    """Handle viral detection mode selection."""
    await settings_db.update_viral_detection_mode(user_id, mode)
    await log_setting_change(user_id, "viral_detection_mode", mode)

    text = f"🔥 Viral detection mode set to *{mode}*."
    await update.callback_query.edit_message_text(
        text, reply_markup=settings_menu_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Help sub-page handlers
# ===========================================================================

async def _handle_help_how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'How It Works' help page."""
    text = (
        "📖 *How It Works*\n\n"
        "1. *Send a video* — YouTube URL or upload an MP4\n"
        "2. *Download* — The bot downloads the video (if YouTube)\n"
        "3. *Transcribe* — Audio is transcribed using AI\n"
        "4. *Detect* — AI finds the most viral moments\n"
        "5. *Clip* — Each moment is trimmed to a Short\n"
        "6. *Process* — Captions, zoom, B-roll, and effects are added\n"
        "7. *Deliver* — Finished Shorts are sent to you in Telegram\n\n"
        "The entire process runs in the background, so you can "
        "continue using the bot while processing."
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=help_keyboard(), parse_mode="Markdown"
    )


async def _handle_help_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Commands' help page."""
    text = (
        "📋 *Available Commands*\n\n"
        "/start — Start the bot and see the main menu\n"
        "/help — Show help information\n"
        "/settings — Open settings menu\n"
        "/history — View your generated Shorts\n"
        "/queue — Check processing queue status\n"
        "/account — View your account info\n\n"
        "*Admin Commands:*\n"
        "/stats — View global statistics\n"
        "/users — List users\n"
        "/broadcast — Send message to all users\n"
        "/cache — View cache status\n"
        "/cleanup — Clean up old files\n"
        "/restart — Restart the bot\n"
        "/logs — View recent logs"
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=help_keyboard(), parse_mode="Markdown"
    )


async def _handle_help_limits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Limits & Rules' help page."""
    text = (
        "⚠ *Limits & Rules*\n\n"
        "*File Upload:*\n"
        "• Maximum file size: 2 GB\n"
        "• Supported formats: MP4, MKV, MOV, AVI, WEBM\n\n"
        "*YouTube:*\n"
        "• Maximum video length: 1 hour\n"
        "• Playlists are not supported\n\n"
        "*Rate Limiting:*\n"
        "• Maximum 10 requests per minute\n"
        "• Queue position is shared across users\n\n"
        "*Processing:*\n"
        "• Each video can generate up to 20 Shorts\n"
        "• Processing time depends on video length\n"
        "• Maximum 2 concurrent jobs per user"
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=help_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Account sub-page handlers
# ===========================================================================

async def _handle_account_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Account Stats sub-page."""
    stats = await stats_db.get_user_stats_summary(user_id)

    text = (
        "📊 *Your Statistics*\n\n"
        f"Jobs Created: {stats['jobs_created']}\n"
        f"Jobs Completed: {stats['jobs_completed']}\n"
        f"Jobs Failed: {stats['jobs_failed']}\n"
        f"Shorts Generated: {stats['shorts_generated']}\n"
        f"Commands Used: {stats['commands_used']}\n"
    )

    await update.callback_query.edit_message_text(
        text, reply_markup=account_keyboard(), parse_mode="Markdown"
    )


async def _handle_account_settings_view(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Account Settings View sub-page."""
    settings = await settings_db.get_or_create_settings(user_id)

    text = (
        "📋 *Your Current Settings*\n\n"
        f"Shorts: `{settings.get('num_shorts', 3)}`\n"
        f"Style: `{settings.get('caption_style', 'hormozi')}`\n"
        f"Font: `{settings.get('caption_font', 'montserrat')}`\n"
        f"Color: `{settings.get('caption_color', '#FFFFFF')}`\n"
        f"Emoji: {'ON' if settings.get('emoji_enabled') else 'OFF'}\n"
        f"Zoom: {'ON' if settings.get('zoom_enabled') else 'OFF'}\n"
        f"B-roll: {'ON' if settings.get('broll_enabled') else 'OFF'}\n"
        f"Silence: {'ON' if settings.get('silence_removal') else 'OFF'}\n"
        f"Quality: `{settings.get('output_quality', 'high')}`\n"
        f"Language: `{settings.get('language', 'auto')}`\n"
        f"Viral: `{settings.get('viral_detection_mode', 'top_3')}`\n"
        f"Auto Upload: {'ON' if settings.get('auto_upload') else 'OFF'}\n"
        f"Delete Temp: {'ON' if settings.get('delete_temp_files') else 'OFF'}\n"
    )

    await update.callback_query.edit_message_text(
        text, reply_markup=account_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Queue management handlers
# ===========================================================================

async def _handle_queue_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Queue Refresh."""
    active_jobs = await jobs_db.get_user_active_jobs(user_id)

    if not active_jobs:
        text = "📈 *Queue*\n\nNo active jobs."
    else:
        text = "📈 *Active Jobs*\n\n"
        for job in active_jobs:
            status = job["status"].title()
            progress = job.get("progress", 0)
            msg = job.get("progress_message", "")
            text += f"• {status} ({progress}%) — {msg}\n"

    await update.callback_query.edit_message_text(
        text, reply_markup=queue_keyboard(), parse_mode="Markdown"
    )


async def _handle_queue_cancel_my(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handle Cancel My Jobs."""
    count = await queue_manager.cancel_user_jobs(user_id)

    text = (
        "❌ *Jobs Cancelled*\n\n"
        f"Cancelled {count} active job(s)."
    )

    await update.callback_query.edit_message_text(
        text, reply_markup=queue_keyboard(), parse_mode="Markdown"
    )
