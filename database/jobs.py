"""
Job queue database operations for the Viral Shorts Bot.

Provides CRUD operations for the ``jobs`` table used by the
background processing queue.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from database.connection import get_connection

logger = logging.getLogger(__name__)

# Valid statuses for a job
VALID_STATUSES = frozenset({
    "pending", "downloading", "transcribing", "analyzing",
    "clipping", "processing", "uploading", "completed", "failed", "cancelled",
})

VALID_SOURCE_TYPES = frozenset({"youtube", "upload"})


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def create_job(
    user_id: int,
    source_type: str,
    source_url: Optional[str] = None,
    source_file_path: Optional[str] = None,
    source_filename: Optional[str] = None,
    num_shorts: int = 3,
    settings_snapshot: Optional[dict] = None,
) -> dict:
    """
    Create a new processing job.

    Returns the created job as a dictionary.
    """
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"Invalid source_type: {source_type}")

    job_id = uuid.uuid4().hex
    settings_json = json.dumps(settings_snapshot) if settings_snapshot else None

    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO jobs (
            job_id, user_id, source_type, source_url, source_file_path,
            source_filename, num_shorts_requested, settings_snapshot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, user_id, source_type, source_url, source_file_path,
         source_filename, num_shorts, settings_json),
    )
    await conn.commit()

    logger.info("Job %s created for user %d (%s)", job_id[:8], user_id, source_type)
    return await get_job(job_id)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_job(job_id: str) -> dict:
    """Fetch a job by its ID. Returns empty dict if not found."""
    conn = await get_connection()
    async with conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else {}


async def get_user_jobs(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """Return the most recent jobs for a given user."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_pending_jobs(limit: int = 50) -> list[dict]:
    """Return all pending jobs, ordered by creation time (FIFO)."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_active_jobs(limit: int = 100) -> list[dict]:
    """Return all jobs that are not terminal (completed/failed/cancelled)."""
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT * FROM jobs
        WHERE status NOT IN ('completed', 'failed', 'cancelled')
        ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_user_active_jobs(user_id: int) -> list[dict]:
    """Return non-terminal jobs for a specific user."""
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT * FROM jobs
        WHERE user_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
        ORDER BY created_at DESC
        """,
        (user_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_job_count_by_status(status: str) -> int:
    """Return the number of jobs with a given status."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT COUNT(*) AS cnt FROM jobs WHERE status = ?", (status,)
    ) as cursor:
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_job_status(job_id: str, status: str, progress: Optional[int] = None,
                             progress_message: Optional[str] = None) -> None:
    """
    Update the status (and optionally progress) of a job.

    If the job reaches a terminal state, sets ``completed_at``.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    terminal_statuses = {"completed", "failed", "cancelled"}
    is_terminal = status in terminal_statuses

    updates = ["status = ?"]
    params: list = [status]

    if progress is not None:
        updates.append("progress = ?")
        params.append(progress)

    if progress_message is not None:
        updates.append("progress_message = ?")
        params.append(progress_message)

    if status == "downloading" or status == "transcribing":
        # First time the job is actively worked on — record started_at
        updates.append("started_at = COALESCE(started_at, datetime('now'))")

    if is_terminal:
        updates.append("completed_at = datetime('now')")

    params.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"

    conn = await get_connection()
    await conn.execute(sql, tuple(params))
    await conn.commit()

    logger.debug("Job %s status updated to %s (progress=%s)", job_id[:8], status, progress)


async def set_job_error(job_id: str, error_message: str) -> None:
    """Record an error message on a job and mark it as failed."""
    conn = await get_connection()
    await conn.execute(
        """
        UPDATE jobs
        SET status = 'failed', error_message = ?, completed_at = datetime('now')
        WHERE job_id = ?
        """,
        (error_message, job_id),
    )
    await conn.commit()
    logger.warning("Job %s failed: %s", job_id[:8], error_message[:200])


async def cancel_job(job_id: str) -> dict:
    """Cancel a job if it is not already terminal."""
    conn = await get_connection()
    await conn.execute(
        """
        UPDATE jobs
        SET status = 'cancelled', completed_at = datetime('now')
        WHERE job_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
        """,
        (job_id,),
    )
    await conn.commit()
    return await get_job(job_id)


async def cancel_user_jobs(user_id: int) -> int:
    """Cancel all non-terminal jobs for a user. Returns the count of cancelled jobs."""
    conn = await get_connection()
    cursor = await conn.execute(
        """
        UPDATE jobs
        SET status = 'cancelled', completed_at = datetime('now')
        WHERE user_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
        """,
        (user_id,),
    )
    await conn.commit()
    count = cursor.rowcount
    logger.info("Cancelled %d jobs for user %d", count, user_id)
    return count


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_job(job_id: str) -> None:
    """Delete a job and its associated history records (CASCADE)."""
    conn = await get_connection()
    await conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    await conn.commit()
    logger.info("Job %s deleted.", job_id[:8])


async def cleanup_old_jobs(days: int = 30) -> int:
    """
    Delete completed/failed/cancelled jobs older than *days* days.
    Returns the number of deleted jobs.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        """
        DELETE FROM jobs
        WHERE status IN ('completed', 'failed', 'cancelled')
          AND completed_at < datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    await conn.commit()
    count = cursor.rowcount
    logger.info("Cleaned up %d old jobs (older than %d days)", count, days)
    return count
