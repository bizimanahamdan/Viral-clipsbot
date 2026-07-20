"""
User database operations for the Viral Shorts Bot.

Provides full CRUD operations for the ``users`` table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from database.connection import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create / Upsert
# ---------------------------------------------------------------------------

async def upsert_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    language_code: str = "en",
) -> dict:
    """
    Insert or update a user record.

    Returns the user row as a dictionary.
    """
    conn = await get_connection()

    await conn.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name, language_code, updated_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            language_code = excluded.language_code,
            updated_at = datetime('now'),
            last_active_at = datetime('now')
        """,
        (user_id, username, first_name, last_name, language_code),
    )
    await conn.commit()

    return await get_user(user_id)


async def update_last_active(user_id: int) -> None:
    """Mark the user as active now."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE users SET last_active_at = datetime('now') WHERE user_id = ?",
        (user_id,),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_user(user_id: int) -> dict:
    """Fetch a single user by ID. Returns an empty dict if not found."""
    conn = await get_connection()
    async with conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return {}
        return dict(row)


async def get_all_users(limit: int = 100, offset: int = 0) -> list[dict]:
    """Return a paginated list of all users ordered by creation date."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_active_users(days: int = 30) -> list[dict]:
    """Return users who have been active within the last *days* days."""
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT * FROM users
        WHERE last_active_at >= datetime('now', ?)
        ORDER BY last_active_at DESC
        """,
        (f"-{days} days",),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_user_count() -> int:
    """Return the total number of registered users."""
    conn = await get_connection()
    async with conn.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def set_admin(user_id: int, is_admin: bool = True) -> None:
    """Grant or revoke admin status for a user."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE users SET is_admin = ? WHERE user_id = ?",
        (int(is_admin), user_id),
    )
    await conn.commit()
    logger.info("User %d admin status set to %s", user_id, is_admin)


async def ban_user(user_id: int, banned: bool = True) -> None:
    """Ban or unban a user."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE users SET is_banned = ? WHERE user_id = ?",
        (int(banned), user_id),
    )
    await conn.commit()
    logger.info("User %d ban status set to %s", user_id, banned)


async def set_premium(user_id: int, premium: bool = True, plan: str = "pro") -> None:
    """Set a user's premium status and plan."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE users SET is_premium = ?, plan = ? WHERE user_id = ?",
        (int(premium), plan, user_id),
    )
    await conn.commit()


async def set_plan(user_id: int, plan: str) -> None:
    """Set a user's subscription plan."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE users SET plan = ? WHERE user_id = ?",
        (plan, user_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_user(user_id: int) -> None:
    """Delete a user and all associated data (CASCADE)."""
    conn = await get_connection()
    await conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    await conn.commit()
    logger.info("User %d deleted.", user_id)


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

async def get_admin_users() -> list[dict]:
    """Return all admin users."""
    conn = await get_connection()
    async with conn.execute("SELECT * FROM users WHERE is_admin = 1") as cursor:
        return [dict(row) async for row in cursor]


async def get_banned_users() -> list[dict]:
    """Return all banned users."""
    conn = await get_connection()
    async with conn.execute("SELECT * FROM users WHERE is_banned = 1") as cursor:
        return [dict(row) async for row in cursor]
