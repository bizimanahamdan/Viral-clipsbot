"""
Telegram command handlers for the Viral Shorts Bot.

Handles all slash commands:
- /start, /help, /settings, /history, /queue, /account
- Admin commands: /stats, /users, /broadcast, /cache, /cleanup, /restart, /logs
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from configuration.config import is_admin
from database import users as users_db
from database import settings as settings_db
from database import history as history_db
from database import jobs as jobs_db
from database import statistics as stats_db
from telegram_handlers.common import (
    main_menu_keyboard,
    help_keyboard,
    account_keyboard,
    queue_keyboard,
    send_main_menu,
    send_settings_menu,
    log_command,
    log_setting_change,
    notify_user,
    notify_user_with_keyboard,
)
from utilities.security import rate_limiter, require_admin
from utilities.queue_manager import queue_manager

logger = logging.getLogger(__name__)


# ===========================================================================
# User Commands
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start — welcome message and user registration.
    """
    user = update.effective_user
    if not user:
        return

    # Rate limit check
    if rate_limiter.is_rate_limited(user.id):
        remaining = rate_limiter.get_reset_seconds(user.id)
        await update.message.reply_text(
            f"⚠️ You are rate limited. Please try again in {remaining:.0f} seconds."
        )
        return

    rate_limiter.register_request(user.id)

    # Register or update user in database
    await users_db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code or "en",
    )

    # Create default settings if needed
    await settings_db.get_or_create_settings(user.id)

    # Log event
    await log_command(user.id, "/start")

    # Welcome message
    name = user.first_name or "there"
    text = (
        f"👋 *Hello, {name}!*\n\n"
        "Welcome to *Viral Shorts Bot*! 🎬\n\n"
        "I convert long YouTube videos and uploaded MP4 files into "
        "viral short-form videos with:\n\n"
        "• AI-powered viral moment detection\n"
        "• Animated word-by-word captions\n"
        "• Dynamic zoom and B-roll\n"
        "• Silence removal and noise cleanup\n"
        "• Optimised for TikTok, Reels & Shorts\n\n"
        "Send me a *YouTube URL* or *upload a video* to get started!\n\n"
        "Use the menu below to explore:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — show help menu."""
    user = update.effective_user
    if not user:
        return

    await log_command(user.id, "/help")

    text = (
        "❓ *Help — How to Use Viral Shorts Bot*\n\n"
        "*Getting Started:*\n"
        "1. Send me a YouTube URL or upload an MP4 file\n"
        "2. The bot will detect the most viral moments\n"
        "3. Each moment becomes a Short with captions\n"
        "4. You'll receive the finished Shorts in Telegram\n\n"
        "*Settings:* /settings\n"
        "Customise captions, style, quality, and more.\n\n"
        "*History:* /history\n"
        "View your previously generated Shorts.\n\n"
        "*Queue:* /queue\n"
        "Check the status of your processing jobs.\n\n"
        "*Account:* /account\n"
        "View your usage statistics.\n\n"
        "Use the buttons below for detailed help:"
    )

    await update.message.reply_text(
        text,
        reply_markup=help_keyboard(),
        parse_mode="Markdown",
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings — show settings menu."""
    user = update.effective_user
    if not user:
        return

    await log_command(user.id, "/settings")
    await send_settings_menu(update, context, user.id)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history — show user's generation history."""
    user = update.effective_user
    if not user:
        return

    await log_command(user.id, "/history")

    # Fetch user's history
    history = await history_db.get_user_history(user.id, limit=20)

    if not history:
        text = (
            "📂 *History*\n\n"
            "You haven't generated any Shorts yet.\n"
            "Send me a YouTube URL or upload a video to get started!"
        )
        await update.message.reply_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
        return

    # Build history message
    text = "📂 *Your Recent Shorts*\n\n"
    for i, record in enumerate(history[:10], 1):
        title = record.get("title") or "Untitled"
        source = record.get("source_url") or record.get("source_filename") or "Unknown"
        duration = record.get("duration_seconds", 0) or 0
        score = record.get("viral_score", 0) or 0
        text += (
            f"*{i}.* {title}\n"
            f"   Source: `{source}`\n"
            f"   Duration: {duration:.0f}s | Viral Score: {score:.1f}\n"
            f"   Created: {record.get('created_at', 'N/A')}\n\n"
        )

    total = await history_db.get_user_history_count(user.id)
    text += f"Showing {min(10, len(history))} of {total} total Shorts."

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /queue — show queue status."""
    user = update.effective_user
    if not user:
        return

    await log_command(user.id, "/queue")

    # Get user's active jobs
    active_jobs = await jobs_db.get_user_active_jobs(user.id)

    if not active_jobs:
        text = (
            "📈 *Queue*\n\n"
            "You have no active jobs.\n\n"
            "Send a YouTube URL or upload a video to start processing!"
        )
        await update.message.reply_text(
            text, reply_markup=queue_keyboard(), parse_mode="Markdown"
        )
        return

    text = "📈 *Your Active Jobs*\n\n"
    for job in active_jobs:
        job_id_short = job["job_id"][:8]
        status = job["status"].title()
        progress = job.get("progress", 0)
        message = job.get("progress_message", "")
        source = job.get("source_url") or job.get("source_filename", "Unknown")
        text += (
            f"*Job {job_id_short}*\n"
            f"   Status: {status}\n"
            f"   Progress: {progress}%\n"
            f"   {message}\n"
            f"   Source: `{source}`\n\n"
        )

    await update.message.reply_text(
        text, reply_markup=queue_keyboard(), parse_mode="Markdown"
    )


async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /account — show account info and stats."""
    user = update.effective_user
    if not user:
        return

    await log_command(user.id, "/account")

    # Get user info
    user_data = await users_db.get_user(user.id)
    stats = await stats_db.get_user_stats_summary(user.id)

    text = (
        "👤 *Your Account*\n\n"
        f"*User ID:* `{user.id}`\n"
        f"*Username:* @{user.username or 'N/A'}\n"
        f"*Name:* {user.first_name or ''} {user.last_name or ''}\n"
        f"*Plan:* {user_data.get('plan', 'free').title()}\n"
        f"*Member Since:* {user_data.get('created_at', 'N/A')}\n\n"
        "*Statistics:*\n"
        f"   Jobs Created: {stats['jobs_created']}\n"
        f"   Jobs Completed: {stats['jobs_completed']}\n"
        f"   Jobs Failed: {stats['jobs_failed']}\n"
        f"   Shorts Generated: {stats['shorts_generated']}\n"
        f"   Commands Used: {stats['commands_used']}\n"
    )

    await update.message.reply_text(
        text, reply_markup=account_keyboard(), parse_mode="Markdown"
    )


# ===========================================================================
# Admin Commands
# ===========================================================================

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /stats — show global bot statistics.
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    await log_command(user.id, "/stats")

    # Gather statistics
    global_stats = await stats_db.get_global_stats_summary()
    user_count = await users_db.get_user_count()
    queue_status = await queue_manager.get_queue_status()

    text = (
        "📊 *Bot Statistics*\n\n"
        f"*Users:* {user_count}\n"
        f"*Jobs Created:* {global_stats.get('jobs_created', 0)}\n"
        f"*Jobs Completed:* {global_stats.get('jobs_completed', 0)}\n"
        f"*Jobs Failed:* {global_stats.get('jobs_failed', 0)}\n"
        f"*Shorts Generated:* {global_stats.get('shorts_generated', 0)}\n"
        f"*Files Uploaded:* {global_stats.get('files_uploaded', 0)}\n"
        f"*Videos Downloaded:* {global_stats.get('videos_downloaded', 0)}\n\n"
        "*Queue:*\n"
        f"   Pending: {queue_status['pending']}\n"
        f"   Running: {queue_status['running']}\n"
        f"   Completed: {queue_status['completed']}\n"
        f"   Failed: {queue_status['failed']}\n"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /users — list recent users.
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    await log_command(user.id, "/users")

    # Parse optional arguments
    args = context.args
    limit = 20
    offset = 0
    show_banned = False

    if args:
        for arg in args:
            if arg.startswith("limit="):
                try:
                    limit = min(int(arg.split("=")[1]), 100)
                except ValueError:
                    pass
            elif arg == "banned":
                show_banned = True
            elif arg.startswith("offset="):
                try:
                    offset = int(arg.split("=")[1])
                except ValueError:
                    pass

    if show_banned:
        users_list = await users_db.get_banned_users()
    else:
        users_list = await users_db.get_all_users(limit=limit, offset=offset)

    if not users_list:
        text = "📋 *Users*\n\nNo users found."
    else:
        text = f"📋 *Recent Users* (showing {len(users_list)}):\n\n"
        for u in users_list[:limit]:
            username = u.get("username") or "N/A"
            name = u.get("first_name") or ""
            plan = u.get("plan", "free").title()
            status = "🚫" if u.get("is_banned") else "✅"
            text += (
                f"{status} `{u['user_id']}` — @{username} "
                f"({name}) — {plan}\n"
            )

    text += f"\nOffset: {offset} | Limit: {limit}"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /broadcast — send a message to all users.
    Usage: /broadcast <message>
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <message>\n\n"
            "Send a message to all registered users."
        )
        return

    message_text = " ".join(context.args)

    # Get all active users (active in last 30 days)
    active_users = await users_db.get_active_users(days=30)

    if not active_users:
        await update.message.reply_text("No active users to broadcast to.")
        return

    # Confirm with admin
    await update.message.reply_text(
        f"📢 *Broadcast*\n\n"
        f"Sending to *{len(active_users)}* users:\n\n"
        f"```\n{message_text[:500]}\n```\n\n"
        f"Type *Yes* to confirm." if len(active_users) > 5 else None,
        parse_mode="Markdown",
    )

    # Send to each user
    success = 0
    failed = 0
    for u in active_users:
        try:
            await context.bot.send_message(
                chat_id=u["user_id"],
                text=message_text,
                parse_mode="Markdown",
            )
            success += 1
        except Exception as e:
            logger.debug("Broadcast failed for user %d: %s", u["user_id"], e)
            failed += 1

    await update.message.reply_text(
        f"📢 *Broadcast Complete*\n\n"
        f"Sent: {success}\n"
        f"Failed: {failed}\n"
        f"Total: {len(active_users)}"
    )


async def cmd_cache(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /cache — show cache status and manage cache.
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    from configuration.config import CACHE_DIR

    # Calculate cache size
    cache_size = 0
    file_count = 0
    for f in CACHE_DIR.glob("*"):
        if f.is_file():
            cache_size += f.stat().st_size
            file_count += 1

    text = (
        "💾 *Cache Status*\n\n"
        f"*Files:* {file_count}\n"
        f"*Size:* {cache_size / (1024*1024):.1f} MB\n"
        f"*Location:* `{CACHE_DIR}`\n\n"
        "Use /cleanup to clear old cache files."
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /cleanup — clean up old files and database records.
    Usage: /cleanup [days] (default: 30)
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    # Parse days argument
    days = 30
    if context.args:
        try:
            days = max(1, min(int(context.args[0]), 365))
        except ValueError:
            pass

    status_msg = await update.message.reply_text("🧹 Cleaning up...")

    # Clean old jobs
    jobs_deleted = await jobs_db.cleanup_old_jobs(days=days)

    # Clean old statistics
    stats_deleted = await stats_db.cleanup_old_statistics(days=days)

    # Clean old files in temp/uploads
    from configuration.config import TEMP_DIR, UPLOADS_DIR

    files_deleted = 0
    cutoff_time = (datetime.now(timezone.utc).timestamp() - days * 86400)

    for directory in [TEMP_DIR, UPLOADS_DIR]:
        for f in directory.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff_time:
                try:
                    f.unlink()
                    files_deleted += 1
                except OSError as e:
                    logger.debug("Failed to delete %s: %s", f, e)

    await status_msg.edit_text(
        f"🧹 *Cleanup Complete*\n\n"
        f"*Days:* {days}\n"
        f"*Jobs Deleted:* {jobs_deleted}\n"
        f"*Stats Deleted:* {stats_deleted}\n"
        f"*Files Deleted:* {files_deleted}"
    )


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /restart — restart the bot process.
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    await update.message.reply_text("🔄 Restarting the bot...")

    # Stop the queue manager gracefully
    await queue_manager.stop()

    # Close the database connection
    from database.connection import close_connection
    await close_connection()

    logger.info("Bot restart initiated by admin %d.", user.id)

    # Exit the process — the process manager (systemd, Docker, etc.) will restart it
    sys.exit(0)


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin /logs — show recent log entries.
    Usage: /logs [lines] (default: 30)
    """
    user = update.effective_user
    if not user:
        return

    is_adm, msg = require_admin(user)
    if not is_adm:
        await update.message.reply_text(msg)
        return

    from configuration.config import LOGS_DIR

    log_file = LOGS_DIR / "viral_shorts.log"

    if not log_file.exists():
        await update.message.reply_text("No log file found.")
        return

    # Parse lines argument
    num_lines = 30
    if context.args:
        try:
            num_lines = max(5, min(int(context.args[0]), 100))
        except ValueError:
            pass

    # Read last N lines
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_lines = lines[-num_lines:]

    text = "📋 *Recent Logs*\n\n```\n"
    text += "".join(last_lines)
    text += "```"

    # Truncate if too long for Telegram
    if len(text) > 4000:
        text = text[:3900] + "\n... (truncated)"

    await update.message.reply_text(text, parse_mode="Markdown")


# ===========================================================================
# Export — list of all handlers for registration
# ===========================================================================

COMMAND_HANDLERS: dict[str, callable] = {
    "start": cmd_start,
    "help": cmd_help,
    "settings": cmd_settings,
    "history": cmd_history,
    "queue": cmd_queue,
    "account": cmd_account,
    # Admin
    "stats": cmd_stats,
    "users": cmd_users,
    "broadcast": cmd_broadcast,
    "cache": cmd_cache,
    "cleanup": cmd_cleanup,
    "restart": cmd_restart,
    "logs": cmd_logs,
}
