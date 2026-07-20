"""
Async job queue manager for the Viral Shorts Bot.

Supports:
- Multiple concurrent users
- Background processing with asyncio
- Progress tracking and callbacks
- Job cancellation
- Resume after restart (loads pending jobs from DB)
- Configurable concurrency limit
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from configuration.config import (
    QUEUE_JOB_TIMEOUT_SECONDS,
    QUEUE_MAX_CONCURRENT_JOBS,
    QUEUE_MAX_RETRIES,
    QUEUE_RETRY_DELAY_SECONDS,
)
from database import jobs as jobs_db
from database import statistics as stats_db
from utilities.logging_config import get_logger

logger = get_logger("queue_manager")


# ===========================================================================
# Job States
# ===========================================================================

class JobStatus(str, Enum):
    """Possible statuses for a queue job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobPriority(int, Enum):
    """Job priority levels (lower = higher priority)."""
    HIGH = 0
    NORMAL = 1
    LOW = 2


# ===========================================================================
# Job data class
# ===========================================================================

class QueueJob:
    """
    Represents a single job in the processing queue.

    Attributes:
        job_id: Unique identifier (matches the DB record).
        user_id: The Telegram user who submitted the job.
        source_type: 'youtube' or 'upload'.
        source_url: URL for YouTube jobs.
        source_file_path: Local path for uploaded files.
        source_filename: Original filename.
        settings: User settings snapshot at job creation.
        status: Current queue status.
        progress: Integer 0-100.
        progress_message: Human-readable progress text.
        retries: Number of retry attempts used.
        started_at: When the job began processing.
        created_at: When the job was enqueued.
        result: Job result data (populated on completion).
        error: Error message if failed.
    """

    def __init__(
        self,
        job_id: str,
        user_id: int,
        source_type: str,
        source_url: Optional[str] = None,
        source_file_path: Optional[str] = None,
        source_filename: Optional[str] = None,
        settings: Optional[dict] = None,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> None:
        self.job_id: str = job_id
        self.user_id: int = user_id
        self.source_type: str = source_type
        self.source_url: Optional[str] = source_url
        self.source_file_path: Optional[str] = source_file_path
        self.source_filename: Optional[str] = source_filename
        self.settings: dict = settings or {}
        self.priority: JobPriority = priority
        self.status: JobStatus = JobStatus.PENDING
        self.progress: int = 0
        self.progress_message: str = ""
        self.retries: int = 0
        self.started_at: Optional[datetime] = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.result: Optional[dict] = None
        self.error: Optional[str] = None


# ===========================================================================
# Queue Manager
# ===========================================================================

class QueueManager:
    """
    Manages the async job queue with background workers.

    Usage::

        manager = QueueManager()
        await manager.start()
        # ... submit jobs ...
        await manager.stop()
    """

    def __init__(
        self,
        max_concurrent: int = QUEUE_MAX_CONCURRENT_JOBS,
        max_retries: int = QUEUE_MAX_RETRIES,
        retry_delay: int = QUEUE_RETRY_DELAY_SECONDS,
        job_timeout: int = QUEUE_JOB_TIMEOUT_SECONDS,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._job_timeout = job_timeout

        # Internal state
        self._queue: asyncio.Queue[QueueJob] = asyncio.Queue()
        self._running_jobs: dict[str, asyncio.Task] = {}
        self._completed_jobs: dict[str, QueueJob] = {}
        self._cancelled_jobs: set[str] = set()
        self._active_workers: int = 0
        self._worker_tasks: list[asyncio.Task] = []
        self._running: bool = False
        self._progress_callbacks: dict[str, Callable] = {}

        # Per-user concurrency tracking
        self._user_active_jobs: dict[int, int] = defaultdict(int)

        logger.info(
            "QueueManager initialised (max_concurrent=%d, max_retries=%d, timeout=%ds)",
            max_concurrent, max_retries, job_timeout,
        )

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Start the queue manager and background workers."""
        if self._running:
            logger.warning("QueueManager is already running.")
            return

        self._running = True

        # Start worker tasks
        for i in range(self._max_concurrent):
            task = asyncio.create_task(self._worker(f"worker-{i}"))
            self._worker_tasks.append(task)

        # Load pending jobs from database for resume-after-restart
        await self._load_pending_jobs()

        logger.info("QueueManager started with %d workers.", self._max_concurrent)

    async def stop(self) -> None:
        """Gracefully stop the queue manager."""
        logger.info("Stopping QueueManager...")
        self._running = False

        # Cancel all worker tasks
        for task in self._worker_tasks:
            task.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

        # Cancel all running jobs
        for job_id, task in self._running_jobs.items():
            task.cancel()

        logger.info("QueueManager stopped.")

    # -----------------------------------------------------------------------
    # Job submission
    # -----------------------------------------------------------------------

    async def submit_job(
        self,
        job: QueueJob,
    ) -> QueueJob:
        """
        Submit a new job to the queue.

        Creates a DB record and enqueues the job for processing.
        """
        # Create database record
        await jobs_db.create_job(
            user_id=job.user_id,
            source_type=job.source_type,
            source_url=job.source_url,
            source_file_path=job.source_file_path,
            source_filename=job.source_filename,
            num_shorts=job.settings.get("num_shorts", 3),
            settings_snapshot=job.settings,
        )

        # Log the event
        await stats_db.log_event(
            event_type="job_created",
            user_id=job.user_id,
            details={"job_id": job.job_id, "source_type": job.source_type},
        )

        # Enqueue
        await self._queue.put(job)
        logger.info("Job %s submitted for user %d", job.job_id[:8], job.user_id)

        return job

    # -----------------------------------------------------------------------
    # Job control
    # -----------------------------------------------------------------------

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a job by ID.

        Returns True if the job was successfully cancelled.
        """
        self._cancelled_jobs.add(job_id)

        # Cancel the running task if it exists
        task = self._running_jobs.pop(job_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Update DB
        await jobs_db.cancel_job(job_id)

        # Remove from progress callbacks
        self._progress_callbacks.pop(job_id, None)

        logger.info("Job %s cancelled.", job_id[:8])
        return True

    async def cancel_user_jobs(self, user_id: int) -> int:
        """Cancel all non-terminal jobs for a user. Returns count cancelled."""
        count = await jobs_db.cancel_user_jobs(user_id)

        # Cancel running tasks
        to_cancel = [
            job_id for job_id, job in self._running_jobs.items()
            if self._get_job_user_id(job_id) == user_id
        ]
        for job_id in to_cancel:
            self._cancelled_jobs.add(job_id)
            task = self._running_jobs.pop(job_id, None)
            if task is not None:
                task.cancel()

        self._user_active_jobs[user_id] = 0
        logger.info("Cancelled %d jobs for user %d", count, user_id)
        return count

    # -----------------------------------------------------------------------
    # Progress tracking
    # -----------------------------------------------------------------------

    def register_progress_callback(
        self,
        job_id: str,
        callback: Callable,
    ) -> None:
        """
        Register a callback that will be called with (progress, message)
        whenever the job's progress is updated.
        """
        self._progress_callbacks[job_id] = callback

    def unregister_progress_callback(self, job_id: str) -> None:
        """Remove the progress callback for a job."""
        self._progress_callbacks.pop(job_id, None)

    async def update_progress(
        self,
        job_id: str,
        progress: int,
        message: str = "",
    ) -> None:
        """
        Update the progress of a job.

        Clips progress to 0-100, updates the DB, and calls the callback.
        """
        progress = max(0, min(100, progress))

        job = self._completed_jobs.get(job_id)
        if job is not None:
            job.progress = progress
            job.progress_message = message

        # Update database
        await jobs_db.update_job_status(
            job_id=job_id,
            status=await self._get_current_db_status(job_id),
            progress=progress,
            progress_message=message,
        )

        # Call progress callback
        callback = self._progress_callbacks.get(job_id)
        if callback:
            try:
                result = callback(progress, message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.debug("Progress callback error for job %s: %s", job_id[:8], e)

    # -----------------------------------------------------------------------
    # Status queries
    # -----------------------------------------------------------------------

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Return the current status of a job."""
        if job_id in self._cancelled_jobs:
            return JobStatus.CANCELLED
        if job_id in self._completed_jobs:
            return self._completed_jobs[job_id].status
        if job_id in self._running_jobs:
            return JobStatus.RUNNING
        # Check if it's in the queue
        # (we can't easily check the asyncio.Queue contents, so we check DB)
        return None

    def get_running_job_count(self) -> int:
        """Return the number of currently running jobs."""
        return len(self._running_jobs)

    def get_queue_size(self) -> int:
        """Return the number of jobs waiting in the queue."""
        return self._queue.qsize()

    def get_user_active_job_count(self, user_id: int) -> int:
        """Return the number of active jobs for a user."""
        return self._user_active_jobs.get(user_id, 0)

    async def get_queue_status(self) -> dict:
        """Return a summary of the current queue state."""
        pending = await jobs_db.get_job_count_by_status("pending")
        running = self.get_running_job_count()
        completed = await jobs_db.get_job_count_by_status("completed")
        failed = await jobs_db.get_job_count_by_status("failed")

        return {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "queue_size": self.get_queue_size(),
            "max_concurrent": self._max_concurrent,
        }

    # -----------------------------------------------------------------------
    # Internal: Worker
    # -----------------------------------------------------------------------

    async def _worker(self, name: str) -> None:
        """
        Background worker that processes jobs from the queue.
        """
        logger.info("Worker %s started.", name)

        while self._running:
            try:
                # Get next job from queue (with timeout so we can check _running)
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if job.job_id in self._cancelled_jobs:
                    logger.info("Skipping cancelled job %s", job.job_id[:8])
                    continue

                # Check user concurrency (max 2 active jobs per user)
                if self._user_active_jobs[job.user_id] >= 2:
                    # Re-queue with lower priority
                    logger.info(
                        "User %d has too many active jobs, re-queuing %s",
                        job.user_id, job.job_id[:8],
                    )
                    await asyncio.sleep(1)
                    await self._queue.put(job)
                    continue

                # Process the job
                self._active_workers += 1
                self._user_active_jobs[job.user_id] += 1
                self._running_jobs[job.job_id] = asyncio.current_task()  # type: ignore

                try:
                    await self._process_job(job)
                except asyncio.CancelledError:
                    job.status = JobStatus.CANCELLED
                    await jobs_db.update_job_status(job.job_id, "cancelled")
                    raise
                except Exception as e:
                    logger.exception("Worker %s error processing job %s: %s", name, job.job_id[:8], e)
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    await jobs_db.set_job_error(job.job_id, str(e))
                    await stats_db.log_event(
                        event_type="job_failed",
                        user_id=job.user_id,
                        details={"job_id": job.job_id, "error": str(e)[:500]},
                    )
                finally:
                    self._running_jobs.pop(job.job_id, None)
                    self._active_workers -= 1
                    self._user_active_jobs[job.user_id] -= 1
                    self._completed_jobs[job.job_id] = job
                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Worker %s unexpected error: %s", name, e)
                await asyncio.sleep(1)

        logger.info("Worker %s stopped.", name)

    async def _process_job(self, job: QueueJob) -> None:
        """
        Process a single job through the pipeline.

        This is the main pipeline orchestrator. In Part 1 we simulate
        the processing stages. In Part 2 the actual AI/video processing
        modules will be connected.
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)

        stages = [
            ("downloading", "Downloading video...", 5),
            ("transcribing", "Transcribing audio...", 20),
            ("analyzing", "Detecting viral moments...", 40),
            ("clipping", "Clipping video segments...", 60),
            ("processing", "Applying captions and effects...", 80),
            ("uploading", "Uploading shorts...", 95),
        ]

        for stage_status, stage_message, stage_progress in stages:
            # Check cancellation
            if job.job_id in self._cancelled_jobs:
                job.status = JobStatus.CANCELLED
                await jobs_db.update_job_status(job.job_id, "cancelled")
                await stats_db.log_event(
                    event_type="job_cancelled",
                    user_id=job.user_id,
                    details={"job_id": job.job_id, "stage": stage_status},
                )
                return

            # Update progress
            await jobs_db.update_job_status(
                job_id=job.job_id,
                status=stage_status,
                progress=stage_progress,
                progress_message=stage_message,
            )
            await self.update_progress(job.job_id, stage_progress, stage_message)

            # Simulate processing delay (will be replaced with actual processing in Part 2)
            await asyncio.sleep(0.5)

        # Mark as completed
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.progress_message = "Processing complete!"
        job.result = {
            "shorts_generated": job.settings.get("num_shorts", 3),
            "total_duration": 0,
        }

        await jobs_db.update_job_status(
            job_id=job.job_id,
            status="completed",
            progress=100,
            progress_message="Processing complete!",
        )

        await stats_db.log_event(
            event_type="job_completed",
            user_id=job.user_id,
            details={"job_id": job.job_id},
        )

        logger.info(
            "Job %s completed for user %d (%s)",
            job.job_id[:8], job.user_id, job.source_type,
        )

    # -----------------------------------------------------------------------
    # Internal: Resume from database
    # -----------------------------------------------------------------------

    async def _load_pending_jobs(self) -> None:
        """
        Load pending jobs from the database to resume after a restart.
        """
        pending = await jobs_db.get_pending_jobs()

        for job_data in pending:
            job = QueueJob(
                job_id=job_data["job_id"],
                user_id=job_data["user_id"],
                source_type=job_data["source_type"],
                source_url=job_data.get("source_url"),
                source_file_path=job_data.get("source_file_path"),
                source_filename=job_data.get("source_filename"),
            )
            # Import settings from JSON snapshot
            if job_data.get("settings_snapshot"):
                import json
                try:
                    job.settings = json.loads(job_data["settings_snapshot"])
                except (json.JSONDecodeError, TypeError):
                    pass

            await self._queue.put(job)
            logger.info("Resumed job %s from database", job.job_id[:8])

        if pending:
            logger.info("Loaded %d pending jobs from database.", len(pending))

    # -----------------------------------------------------------------------
    # Internal: Helpers
    # -----------------------------------------------------------------------

    def _get_job_user_id(self, job_id: str) -> Optional[int]:
        """Get the user_id for a job from running or completed jobs."""
        job = self._running_jobs.get(job_id)
        if job is not None:
            return self._completed_jobs.get(job_id, QueueJob(job_id, 0, "unknown")).user_id
        completed = self._completed_jobs.get(job_id)
        if completed:
            return completed.user_id
        return None

    async def _get_current_db_status(self, job_id: str) -> str:
        """Get the current status string from the database for a job."""
        job_data = await jobs_db.get_job(job_id)
        if job_data:
            return job_data.get("status", "pending")
        return "pending"


# ===========================================================================
# Singleton instance
# ===========================================================================

queue_manager = QueueManager()
