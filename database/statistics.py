"""
Statistics database operations for the Viral Shorts Bot.

Records events for analytics and provides aggregation queries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from database.connection import get_connection

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = frozenset({
    "job_created", "job_completed", "job_failed", "job_cancelled",
    "short_generated", "command_used", "setting_changed",
    "file_uploaded", "video_downloaded", "transcription_done",
    "caption_generated", "viral_analysis_done",
})


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def log_event(
    event_type: str,
    user_id: Optional[int] = None,
    details: Optional[dict] = None,
) -> int:
    """
    Log a statistics event.

    Returns the auto-incremented stat_id.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")

    details_json = json.dumps(details) if details else None

    conn = await get_connection()
    cursor = await conn.execute(
        "INSERT INTO statistics (user_id, event_type, details) VALUES (?, ?, ?)",
        (user_id, event_type, details_json),
    )
    await conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Read — aggregation helpers
# ---------------------------------------------------------------------------

async def get_event_count(event_type: str) -> int:
    """Return the total number of events of a given type."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT COUNT(*) AS cnt FROM statistics WHERE event_type = ?", (event_type,)
    ) as cursor:
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


async def get_event_count_by_user(user_id: int, event_type: Optional[str] = None) -> int:
    """Return the event count for a specific user, optionally filtered by event type."""
    conn = await get_connection()
    if event_type:
        async with conn.execute(
            "SELECT COUNT(*) AS cnt FROM statistics WHERE user_id = ? AND event_type = ?",
            (user_id, event_type),
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0
    else:
        async with conn.execute(
            "SELECT COUNT(*) AS cnt FROM statistics WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0


async def get_recent_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    user_id: Optional[int] = None,
) -> list[dict]:
    """Return the most recent events, optionally filtered."""
    conn = await get_connection()

    conditions = []
    params: list = []

    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    sql = f"SELECT * FROM statistics {where_clause} ORDER BY created_at DESC LIMIT ?"

    async with conn.execute(sql, tuple(params)) as cursor:
        return [dict(row) async for row in cursor]


async def get_user_stats_summary(user_id: int) -> dict:
    """
    Return a summary of statistics for a user.

    Returns:
        dict with keys:
            total_events, jobs_created, jobs_completed, jobs_failed,
            shorts_generated, commands_used
    """
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT
            COUNT(*) AS total_events,
            SUM(CASE WHEN event_type = 'job_created' THEN 1 ELSE 0 END) AS jobs_created,
            SUM(CASE WHEN event_type = 'job_completed' THEN 1 ELSE 0 END) AS jobs_completed,
            SUM(CASE WHEN event_type = 'job_failed' THEN 1 ELSE 0 END) AS jobs_failed,
            SUM(CASE WHEN event_type = 'short_generated' THEN 1 ELSE 0 END) AS shorts_generated,
            SUM(CASE WHEN event_type = 'command_used' THEN 1 ELSE 0 END) AS commands_used
        FROM statistics
        WHERE user_id = ?
        """,
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return {
                "total_events": 0, "jobs_created": 0, "jobs_completed": 0,
                "jobs_failed": 0, "shorts_generated": 0, "commands_used": 0,
            }
        return {k: (v or 0) for k, v in dict(row).items()}


async def get_global_stats_summary() -> dict:
    """
    Return a global summary of all statistics across all users.
    """
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT
            COUNT(*) AS total_events,
            COUNT(DISTINCT user_id) AS unique_users,
            SUM(CASE WHEN event_type = 'job_created' THEN 1 ELSE 0 END) AS jobs_created,
            SUM(CASE WHEN event_type = 'job_completed' THEN 1 ELSE 0 END) AS jobs_completed,
            SUM(CASE WHEN event_type = 'job_failed' THEN 1 ELSE 0 END) AS jobs_failed,
            SUM(CASE WHEN event_type = 'short_generated' THEN 1 ELSE 0 END) AS shorts_generated,
            SUM(CASE WHEN event_type = 'command_used' THEN 1 ELSE 0 END) AS commands_used,
            SUM(CASE WHEN event_type = 'file_uploaded' THEN 1 ELSE 0 END) AS files_uploaded,
            SUM(CASE WHEN event_type = 'video_downloaded' THEN 1 ELSE 0 END) AS videos_downloaded
        FROM statistics
        """
    ) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return {}
        return {k: (v or 0) for k, v in dict(row).items()}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def cleanup_old_statistics(days: int = 90) -> int:
    """
    Delete statistics records older than *days* days.
    Returns the number of deleted records.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        "DELETE FROM statistics WHERE created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    await conn.commit()
    count = cursor.rowcount
    logger.info("Cleaned up %d old statistics records (older than %d days)", count, days)
    return count
