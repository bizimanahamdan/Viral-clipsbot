"""
Logging configuration for the Viral Shorts Bot using Rich.

Provides structured, colourised logging output to both the console
and a rotating log file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

from configuration.config import LOGS_DIR

# ---------------------------------------------------------------------------
# Custom Rich theme for log output
# ---------------------------------------------------------------------------

_CUSTOM_THEME = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "error": "bold red",
    "critical": "bold white on red",
    "debug": "green",
})

_console: Console = Console(theme=_CUSTOM_THEME, stderr=True)


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger with Rich handlers.

    This sets up:
    - A Rich console handler (colourised, with timestamp)
    - A file handler writing to logs/viral_shorts.log

    Safe to call multiple times — idempotent.
    """
    log_file = LOGS_DIR / "viral_shorts.log"

    # Create a root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # ---- Rich console handler ----
    rich_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=True,
        show_level=True,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setLevel(level)
    root_logger.addHandler(rich_handler)

    # ---- File handler (plain text for grep/search) ----
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    logging.info("Logging configured (level=%s, file=%s)", logging.getLevelName(level), log_file)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger with the project's root namespace.

    Example::

        logger = get_logger("video_processing.ffmpeg")
    """
    return logging.getLogger(f"viral_shorts.{name}")
