"""
Database connection management for the Viral Shorts Bot.

Provides a singleton connection pool and initialises the SQLite database
with the schema defined in ``schema.py``.
"""

from __future__ import annotations

import aiosqlite
import logging
from pathlib import Path
from typing import Optional

from configuration.config import DATABASE_PATH
from database.schema import ALL_SCHEMA_STATEMENTS

logger = logging.getLogger(__name__)

# Singleton connection (SQLite is file-based and supports concurrent reads)
_db: Optional[aiosqlite.Connection] = None


async def get_connection() -> aiosqlite.Connection:
    """Return the global aiosqlite connection, creating it if needed."""
    global _db

    if _db is None or not _db.is_alive():
        _db = await aiosqlite.connect(str(DATABASE_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL;")
        await _db.execute("PRAGMA busy_timeout=5000;")
        await _db.execute("PRAGMA foreign_keys=ON;")
        await _db.commit()
        logger.info("Database connection established: %s", DATABASE_PATH)

    return _db


async def init_database() -> None:
    """
    Create all tables and indexes if they do not exist.
    Safe to call multiple times — all statements use ``IF NOT EXISTS``.
    """
    conn = await get_connection()

    for statement in ALL_SCHEMA_STATEMENTS:
        await conn.execute(statement)

    await conn.commit()
    logger.info("Database schema initialised successfully.")


async def close_connection() -> None:
    """Close the database connection gracefully."""
    global _db

    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed.")
