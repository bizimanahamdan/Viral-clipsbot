"""
Video Downloader — yt-dlp integration for YouTube downloads.

Downloads YouTube videos with:
- 1080p resolution preference (bestvideo[height<=1080])
- Highest quality audio/video with MP4 merge
- Retry logic with exponential backoff
- Playlist rejection
- Progress callbacks
- File size validation
- Duration validation
- Video info extraction without download
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Awaitable

from configuration.config import (
    TEMP_DIR,
    UPLOADS_DIR,
    MAX_DOWNLOAD_SIZE_BYTES,
    MAX_YOUTUBE_DURATION_SECONDS,
    FFMPEG_MAX_DURATION_SECONDS,
)
from utilities.logging_config import get_logger

logger = get_logger("video_processing.downloader")


@dataclass
class DownloadResult:
    """Result of a video download operation."""
    file_path: Path
    title: str
    duration: float
    resolution: str
    file_size: int
    source_url: str
    thumbnail_url: Optional[str] = None
    uploader: str = ""
    video_id: str = ""


@dataclass
class DownloadProgress:
    """Tracks download progress for a single download."""

    def __init__(self) -> None:
        self.filename: str = ""
        self.status: str = "downloading"
        self.downloaded_bytes: int = 0
        self.total_bytes: int = 0
        self.speed: float = 0.0
        self.eta: float = 0.0
        self.progress_pct: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.status == "finished"

    @property
    def error(self) -> Optional[str]:
        return "Download failed" if self.status == "error" else None


class VideoDownloader:
    """
    Downloads videos from YouTube using yt-dlp.

    Handles format selection, retry logic, progress tracking,
    and validation of downloaded files.
    """

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """
        Initialize the video downloader.

        Args:
            download_dir: Directory to save downloaded files.
            max_retries: Maximum number of download retries.
            retry_delay: Delay between retries in seconds.
        """
        self.download_dir = download_dir or TEMP_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def download(
        self,
        url: str,
        progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None,
    ) -> DownloadResult:
        """
        Download a YouTube video with retries and progress tracking.

        Args:
            url: YouTube video URL.
            progress_callback: Optional async callback(percentage, status_message).

        Returns:
            DownloadResult with file path and metadata.

        Raises:
            RuntimeError: If download fails after all retries.
            ValueError: If URL is a playlist or unsupported.
        """
        logger.info("Downloading video from: %s", url)

        for attempt in range(self.max_retries):
            try:
                result = await self._attempt_download(url, progress_callback)
                logger.info(
                    "Download complete: %s (%s, %.1fs)",
                    result.title, result.resolution, result.duration,
                )
                return result
            except Exception as e:
                logger.warning("Download attempt %d/%d failed: %s", attempt + 1, self.max_retries, e)
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.info("Retrying in %.1f seconds...", delay)
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(f"Download failed after {self.max_retries} attempts: {e}")

        raise RuntimeError("Download exhausted all retries")

    async def _attempt_download(
        self,
        url: str,
        progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None,
    ) -> DownloadResult:
        """
        Single download attempt using yt-dlp library.

        Downloads the highest quality video (up to 1080p) with the
        best audio track merged together into MP4.
        """
        import yt_dlp

        # Validate URL is not a playlist
        if "playlist" in url.lower() and "list=" in url:
            raise ValueError("Playlists are not supported. Please provide a single video URL.")

        progress = DownloadProgress()

        def _progress_hook(d: dict) -> None:
            if d["status"] == "downloading":
                progress.filename = d.get("filename", "")
                progress.downloaded_bytes = d.get("downloaded_bytes", 0)
                progress.total_bytes = d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0)
                progress.speed = d.get("speed", 0) or 0
                progress.eta = d.get("eta", 0) or 0
                if progress.total_bytes > 0:
                    progress.progress_pct = (progress.downloaded_bytes / progress.total_bytes) * 100
            elif d["status"] == "finished":
                progress.status = "finished"
                progress.progress_pct = 100.0

        ydl_opts = {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [_progress_hook],
            "noplaylist": True,
            "nocheckcertificates": False,
            "retries": 3,
            "fragment_retries": 3,
            "ignoreerrors": False,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "postprocessors": [],
        }

        # Size limit
        if MAX_DOWNLOAD_SIZE_BYTES > 0:
            ydl_opts["max_filesize"] = MAX_DOWNLOAD_SIZE_BYTES

        # Duration limit
        if FFMPEG_MAX_DURATION_SECONDS > 0:
            ydl_opts["max_duration"] = FFMPEG_MAX_DURATION_SECONDS

        logger.info("Starting yt-dlp download...")

        loop = asyncio.get_event_loop()

        def _run_dl():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info is None:
                        raise RuntimeError("yt-dlp returned no info")
                    filename = ydl.prepare_filename(info)
                    return info, filename
            except yt_dlp.utils.DownloadError as e:
                raise RuntimeError(f"yt-dlp download error: {e}")
            except yt_dlp.utils.ExtractorError as e:
                raise ValueError(f"yt-dlp extraction error: {e}")

        info, filename = await loop.run_in_executor(None, _run_dl)

        video_path = Path(filename)
        if not video_path.exists():
            raise RuntimeError(f"Downloaded file not found: {video_path}")

        # Find thumbnail
        thumbnail_url = None
        thumb_base = video_path.with_suffix(".jpg")
        if thumb_base.exists():
            thumbnail_url = str(thumb_base)
        thumb_webp = video_path.with_suffix(".webp")
        if thumb_webp.exists():
            thumbnail_url = str(thumb_webp)

        result = DownloadResult(
            file_path=video_path,
            title=info.get("title", video_path.stem),
            duration=float(info.get("duration", 0)),
            resolution=info.get("resolution", "1080p"),
            file_size=video_path.stat().st_size,
            source_url=url,
            thumbnail_url=thumbnail_url,
            uploader=info.get("uploader", ""),
            video_id=info.get("id", ""),
        )

        if progress_callback:
            await progress_callback(100, "Download complete")

        return result

    async def get_video_info(self, url: str) -> dict:
        """
        Get video metadata without downloading.

        Returns dict with title, duration, thumbnail, uploader, etc.
        """
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
        }

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    "id": info.get("id", ""),
                    "title": info.get("title", ""),
                    "duration": float(info.get("duration", 0)),
                    "thumbnail": info.get("thumbnail", ""),
                    "uploader": info.get("uploader", ""),
                    "view_count": info.get("view_count", 0),
                    "description": (info.get("description", "") or "")[:500],
                    "resolution": info.get("resolution", "unknown"),
                    "channel": info.get("channel", ""),
                    "upload_date": info.get("upload_date", ""),
                }

        return await loop.run_in_executor(None, _extract)


# Module-level convenience functions

async def download_youtube_video(
    url: str,
    output_dir: Optional[Path] = None,
    on_progress=None,
) -> Path:
    """
    Download a YouTube video at highest quality (convenience function).

    Args:
        url: YouTube video URL.
        output_dir: Directory to save the downloaded video.
        on_progress: Optional async callback(progress, message).

    Returns:
        Path to the downloaded video file.
    """
    downloader = VideoDownloader(download_dir=output_dir)
    result = await downloader.download(url, on_progress)
    return result.file_path


async def get_video_info(url: str) -> dict:
    """
    Get metadata about a YouTube video without downloading.

    Returns:
        dict with title, duration, thumbnail, uploader, etc.
    """
    downloader = VideoDownloader()
    return await downloader.get_video_info(url)
