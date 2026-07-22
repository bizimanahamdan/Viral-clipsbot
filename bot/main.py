from __future__ import annotations

import asyncio
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import signal
import sys
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Initialize FFmpeg static binaries
# ---------------------------------------------------------------------------
import static_ffmpeg
static_ffmpeg.add_paths()

# ---------------------------------------------------------------------------
# Dummy HTTP Server for Render Port-Binding
# ---------------------------------------------------------------------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

server_thread = threading.Thread(target=run_dummy_server, daemon=True)
server_thread.start()

# ---------------------------------------------------------------------------
# Ensure the project root is on the Python path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import configuration FIRST (loads .env)
# ---------------------------------------------------------------------------
from configuration.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_IDS,
    TELEGRAM_POLLING_INTERVAL,
    TELEGRAM_ALLOWED_UPDATES,
    validate_config,
)

# ---------------------------------------------------------------------------
# Import logging configuration
# ---------------------------------------------------------------------------
from utilities.logging_config import configure_logging, get_logger

# Configure logging immediately
configure_logging(level=logging.INFO)

logger = get_logger("bot.main")


# ---------------------------------------------------------------------------
# Validate configuration
# ---------------------------------------------------------------------------
def validate_startup_config() -> None:
    """
    Validate all required configuration values before starting.
    Exits with error if critical values are missing.
    """
    issues = validate_config()
    if issues:
        logger.critical("Configuration errors detected:")
        for issue in issues:
            logger.critical("  - %s", issue)
        sys.exit(1)

    logger.info("Configuration validated successfully.")
    logger.info("Admin IDs: %s", TELEGRAM_ADMIN_IDS)


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

def register_handlers(application) -> None:
    """
    Register all Telegram handlers with the application.

    This includes:
    - Command handlers (/start, /help, /settings, etc.)
    - Callback query handler (inline buttons)
    - Message handlers (text, documents, videos)
    - Error handler
    """
    from telegram.ext import (
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )
    from telegram_handlers.commands import COMMAND_HANDLERS
    from telegram_handlers.callbacks import handle_callback_query
    from telegram_handlers.messages import (
        handle_text_message,
        handle_document_message,
        handle_video_message,
    )

    # Command handlers
    for command_name, handler_func in COMMAND_HANDLERS.items():
        application.add_handler(CommandHandler(command_name, handler_func))

    # Callback query handler (inline buttons)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Message handlers — order matters! More specific first.
    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.VIDEO,
            handle_video_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message,
        )
    )

    logger.info("All handlers registered successfully.")


async def error_handler(update: object, context) -> None:
    """
    Global error handler for the Telegram bot.

    Logs the error and optionally notifies the admin.
    """
    logger.exception("Exception while handling an update: %s", context.error)

    # Notify admin about critical errors
    if TELEGRAM_ADMIN_IDS and context.error:
        error_msg = f"⚠️ Bot Error:\n```\n{str(context.error)[:500]}\n```"
        for admin_id in TELEGRAM_ADMIN_IDS[:3]:  # Limit notifications
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=error_msg,
                    parse_mode="Markdown",
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Shutdown handling
# ---------------------------------------------------------------------------

_shutdown_event: asyncio.Event | None = None


async def graceful_shutdown(application) -> None:
    """
    Gracefully shut down the bot and queue manager.
    """
    logger.info("Graceful shutdown initiated...")

    # Stop the queue manager
    from utilities.queue_manager import queue_manager
    await queue_manager.stop()

    # Close database
    from database.connection import close_connection
    await close_connection()

    # Stop the application
    await application.stop()

    logger.info("Shutdown complete.")


def handle_signal(signum, frame) -> None:
    """Handle OS signals for graceful shutdown."""
    logger.info("Received signal %d", signum)
    if _shutdown_event:
        _shutdown_event.set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """
    Main async entry point.

    1. Validates configuration
    2. Initialises the database
    3. Starts the queue manager
    4. Creates and configures the Telegram application
    5. Starts long-polling
    """
    global _shutdown_event

    logger.info("=" * 60)
    logger.info("  Viral Shorts Bot — Starting up")
    logger.info("=" * 60)

    # Validate configuration
    validate_startup_config()

    # Initialise database
    logger.info("Initialising database...")
    from database.connection import init_database
    await init_database()

    # Create admin users if not already in DB
    from database import users as users_db
    for admin_id in TELEGRAM_ADMIN_IDS:
        await users_db.upsert_user(user_id=admin_id)
        await users_db.set_admin(admin_id, is_admin=True)

    # Start queue manager
    logger.info("Starting queue manager...")
    from utilities.queue_manager import queue_manager
    await queue_manager.start()

    # Register signal handlers
    _shutdown_event = asyncio.Event()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Create Telegram application
    from telegram import Bot
    from telegram.ext import ApplicationBuilder

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .post_stop(_post_stop)
        .build()
    )

    # Register all handlers
    register_handlers(application)

    # Set error handler
    application.add_error_handler(error_handler)

    # Start the application
    logger.info("Starting Telegram bot...")
    await application.initialize()
    await application.start()

    # Start polling
    logger.info("Starting long-polling...")
    await application.updater.start_polling(
        poll_interval=TELEGRAM_POLLING_INTERVAL,
        allowed_updates=TELEGRAM_ALLOWED_UPDATES,
        drop_pending_updates=True,
    )

    logger.info("=" * 60)
    logger.info("  Bot is now running! Press Ctrl+C to stop.")
    logger.info("=" * 60)

    # Wait for shutdown signal
    try:
        await _shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    # Graceful shutdown
    await graceful_shutdown(application)


async def _post_init(application) -> None:
    """Called after the application is initialised."""
    logger.info("Application post-init complete.")
    # Set bot commands for the menu
    from telegram import BotCommand
    commands = [
        BotCommand("start", "Start the bot and see the main menu"),
        BotCommand("help", "Show help information"),
        BotCommand("settings", "Open settings menu"),
        BotCommand("history", "View your generated Shorts"),
        BotCommand("queue", "Check processing queue status"),
        BotCommand("account", "View your account info"),
    ]

    # Admin commands
    if TELEGRAM_ADMIN_IDS:
        commands.extend([
            BotCommand("stats", "[Admin] View global statistics"),
            BotCommand("users", "[Admin] List users"),
            BotCommand("broadcast", "[Admin] Send message to all users"),
            BotCommand("cache", "[Admin] View cache status"),
            BotCommand("cleanup", "[Admin] Clean up old files"),
            BotCommand("restart", "[Admin] Restart the bot"),
            BotCommand("logs", "[Admin] View recent logs"),
        ])

    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set (%d commands).", len(commands))


async def _post_stop(application) -> None:
    """Called after the application stops."""
    logger.info("Application post-stop complete.")


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
    
