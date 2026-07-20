"""
History database operations for the Viral Shorts Bot.

Stores records of generated short-form videos linked to their parent jobs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from database.connection import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def add_history_record(
    job_id: str,
    user_id: int,
    short_index: int,
    source_url: Optional[str] = None,
    source_filename: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    hashtags: Optional[str] = None,
    hook: Optional[str] = None,
    pinned_comment: Optional[str] = None,
    output_file_path: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    srt_file_path: Optional[str] = None,
    transcript_path: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    viral_score: Optional[float] = None,
) -> dict:
    """
    Create a history record for a generated short.

    Returns the inserted record as a dictionary.
    """
    history_id = uuid.uuid4().hex

    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO history (
            history_id, job_id, user_id, source_url, source_filename,
            short_index, title, description, hashtags, hook, pinned_comment,
            output_file_path, thumbnail_path, srt_file_path, transcript_path,
            duration_seconds, viral_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            history_id, job_id, user_id, source_url, source_filename,
            short_index, title, description, hashtags, hook, pinned_comment,
            output_file_path, thumbnail_path, srt_file_path, transcript_path,
            duration_seconds, viral_score,
        ),
    )
    await conn.commit()

    logger.info(
        "History record %s added for job %s, short #%d",
        history_id[:8], job_id[:8], short_index,
    )
    return await get_history_record(history_id)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_history_record(history_id: str) -> dict:
    """Fetch a single history record by ID. Empty dict if not found."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM history WHERE history_id = ?", (history_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else {}


async def get_history_by_job(job_id: str) -> list[dict]:
    """Return all history records for a specific job."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM history WHERE job_id = ? ORDER BY short_index ASC", (job_id,)
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_user_history(user_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    """Return recent history records for a user."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM history WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_user_history_count(user_id: int) -> int:
    """Return the total number of history records for a user."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT COUNT(*) AS cnt FROM history WHERE user_id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


async def get_total_shorts_generated() -> int:
    """Return the total number of shorts generated across all users."""
    conn = await get_connection()
    async with conn.execute("SELECT COUNT(*) AS cnt FROM history") as cursor:
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_telegram_delivery(
    history_id: str,
    message_id: Optional[int] = None,
    file_id: Optional[str] = None,
) -> None:
    """Record the Telegram message/file IDs after a short is delivered."""
    conn = await get_connection()
    updates = []
    params: list = []

    if message_id is not None:
        updates.append("telegram_message_id = ?")
        params.append(message_id)

    if file_id is not None:
        updates.append("telegram_file_id = ?")
        params.append(file_id)

    if not updates:
        return

    params.append(history_id)
    sql = f"UPDATE history SET {', '.join(updates)} WHERE history_id = ?"

    await conn.execute(sql, tuple(params))
    await conn.commit()
    logger.debug("Updated Telegram delivery info for history %s", history_id[:8])


async def update_history_record(history_id: str, **kwargs) -> dict:
    """
    Update arbitrary fields on a history record.

    Only keys that map to valid columns are applied.
    Returns the updated record.
    """
    valid_columns = {
        "title", "description", "hashtags", "hook", "pinned_comment",
        "output_file_path", "thumbnail_path", "srt_file_path",
        "transcript_path", "duration_seconds", "viral_score",
        "telegram_message_id", "telegram_file_id",
    }

    filtered = {k: v for k, v in kwargs.items() if k in valid_columns}
    if not filtered:
        return await get_history_record(history_id)

    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [history_id]

    conn = await get_connection()
    await conn.execute(f"UPDATE history SET {set_clause} WHERE history_id = ?", values)
    await conn.commit()

    return await get_history_record(history_id)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_history_record(history_id: str) -> None:
    """Delete a single history record."""
    conn = await get_connection()
    await conn.execute("DELETE FROM history WHERE history_id = ?", (history_id,))
    await conn.commit()
    logger.info("History record %s deleted.", history_id[:8])


async def delete_user_history(user_id: int) -> int:
    """Delete all history records for a user. Returns count deleted."""
    conn = await get_connection()
    cursor = await conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    await conn.commit()
    count = cursor.rowcount
    logger.info("Deleted %d history records for user %d", count, user_id)
    return count
