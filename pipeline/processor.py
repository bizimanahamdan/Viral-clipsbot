"""
Pipeline Processor — End-to-end orchestration of the viral shorts creation flow.

Coordinates all modules in sequence:
  1. Download video (YouTube URL or use uploaded file)
  2. Extract audio with normalization
  3. Transcribe audio via Groq Whisper
  4. Detect viral moments with LLM analysis
  5. Generate viral titles, descriptions, hashtags
  6. Clip video at viral moments
  7. Auto-reframe to 9:16 with face tracking
  8. Generate animated captions
  9. Insert emojis based on context
  10. Apply zoom effects
  11. Add B-roll overlays
  12. Render final output
  13. Deliver via Telegram

Each step is independently cancellable and progress is reported
back through the job queue system.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable, Awaitable

from configuration.config import (
    TEMP_DIR, OUTPUTS_DIR, MAX_SHORTS_COUNT,
    MAX_SHORTS_DURATION_SECONDS, BROLL_DIRS,
)
from utilities.logging_config import get_logger

logger = get_logger("pipeline.processor")


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class PipelineStage(Enum):
    """Pipeline processing stages."""
    DOWNLOAD = auto()
    EXTRACT_AUDIO = auto()
    TRANSCRIBE = auto()
    DETECT_VIRAL = auto()
    GENERATE_TITLES = auto()
    CLIP = auto()
    REFRAME = auto()
    CAPTIONS = auto()
    EMOJI = auto()
    ZOOM = auto()
    BROLL = auto()
    RENDER = auto()
    COMPLETE = auto()


class PipelineStatus(Enum):
    """Overall pipeline status."""
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class PipelineProgress:
    """Progress information for the pipeline."""
    stage: PipelineStage
    stage_name: str
    progress: float  # 0.0 to 1.0
    message: str
    elapsed_time: float = 0.0
    current_short: int = 0
    total_shorts: int = 1


@dataclass
class PipelineResult:
    """Final result of the pipeline."""
    success: bool
    output_files: list[Path] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    error_message: str = ""
    total_duration: float = 0.0
    total_size: int = 0


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""
    source_url: Optional[str] = None
    source_file: Optional[Path] = None
    num_shorts: int = 1
    caption_style: str = "hormozi"
    caption_color: str = "#FFFFFF"
    caption_font: str = ""
    emoji_enabled: bool = True
    zoom_enabled: bool = True
    broll_enabled: bool = True
    silence_removal: bool = True
    output_quality: str = "high"
    language: str = "auto"
    viral_detection_mode: str = "aggressive"
    temp_dir: Optional[Path] = None
    output_dir: Optional[Path] = None


# ---------------------------------------------------------------------------
# Pipeline Processor
# ---------------------------------------------------------------------------

class PipelineProcessor:
    """
    End-to-end pipeline orchestrator for viral shorts creation.

    Manages the full flow from input to output, with progress
    tracking, cancellation support, and error handling.
    """

    def __init__(
        self,
        config: PipelineConfig,
        job_id: Optional[str] = None,
        progress_callback: Optional[Callable[[PipelineProgress], Awaitable[None]]] = None,
    ):
        """
        Initialize the pipeline processor.

        Args:
            config: Pipeline configuration.
            job_id: Unique job identifier.
            progress_callback: Async callback for progress updates.
        """
        self.config = config
        self.job_id = job_id or "unknown"
        self.progress_callback = progress_callback
        self.status = PipelineStatus.IDLE
        self.current_stage = PipelineStage.DOWNLOAD
        self.progress = 0.0
        self.cancel_flag = asyncio.Event()
        self.error: Optional[str] = None

        # Intermediate results
        self._video_path: Optional[Path] = None
        self._transcript: Optional[dict] = None
        self._viral_moments: Optional[list[dict]] = None
        self._titles_data: Optional[dict] = None
        self._output_files: list[Path] = []

        # Directories
        self.temp_dir = config.temp_dir or TEMP_DIR / f"job_{self.job_id}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = config.output_dir or OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run(self) -> PipelineResult:
        """
        Execute the full pipeline.

        Returns:
            PipelineResult with output files and metadata.
        """
        start_time = time.monotonic()
        self.status = PipelineStatus.RUNNING

        logger.info(
            "Starting pipeline job=%s source=%s shorts=%d",
            self.job_id,
            self.config.source_url or self.config.source_file,
            self.config.num_shorts,
        )

        try:
            # Step 1: Download or validate source
            await self._report_progress(PipelineStage.DOWNLOAD, "Downloading source video...", 0.0)
            self._video_path = await self._step_download()
            self._check_cancelled()

            # Step 2: Extract audio
            await self._report_progress(PipelineStage.EXTRACT_AUDIO, "Extracting and normalizing audio...", 0.1)
            audio_path = await self._step_extract_audio(self._video_path)
            self._check_cancelled()

            # Step 3: Transcribe
            await self._report_progress(PipelineStage.TRANSCRIBE, "Transcribing audio...", 0.2)
            self._transcript = await self._step_transcribe(audio_path)
            self._check_cancelled()

            # Step 4: Detect viral moments
            await self._report_progress(PipelineStage.DETECT_VIRAL, "Analyzing for viral moments...", 0.3)
            self._viral_moments = await self._step_detect_viral(self._transcript)
            self._check_cancelled()

            # Step 5: Generate titles
            await self._report_progress(PipelineStage.GENERATE_TITLES, "Generating viral titles...", 0.4)
            self._titles_data = await self._step_generate_titles(self._transcript)
            self._check_cancelled()

            # Step 6-12: Process each short
            num_shorts = min(self.config.num_shorts, len(self._viral_moments) if self._viral_moments else self.config.num_shorts)
            num_shorts = max(1, num_shorts)

            for short_idx in range(num_shorts):
                await self._report_progress(
                    PipelineStage.CLIP,
                    f"Processing short {short_idx + 1}/{num_shorts}...",
                    0.5 + (short_idx * 0.5 / num_shorts),
                    current_short=short_idx + 1,
                    total_shorts=num_shorts,
                )

                output_file = await self._process_single_short(short_idx, num_shorts)
                self._output_files.append(output_file)

                self._check_cancelled()

            # Mark complete
            self.status = PipelineStatus.COMPLETED
            elapsed = time.monotonic() - start_time

            logger.info(
                "Pipeline complete: job=%s, %d shorts, %.1fs",
                self.job_id, len(self._output_files), elapsed,
            )

            total_size = sum(f.stat().st_size for f in self._output_files if f.exists())

            return PipelineResult(
                success=True,
                output_files=self._output_files,
                titles=self._titles_data.get("titles", []) if self._titles_data else [],
                descriptions=self._titles_data.get("descriptions", []) if self._titles_data else [],
                hashtags=self._titles_data.get("hashtags", []) if self._titles_data else [],
                total_duration=elapsed,
                total_size=total_size,
            )

        except asyncio.CancelledError:
            self.status = PipelineStatus.CANCELLED
            return PipelineResult(success=False, error_message="Pipeline cancelled")
        except Exception as e:
            self.status = PipelineStatus.FAILED
            self.error = str(e)
            logger.error("Pipeline failed: job=%s, error=%s", self.job_id, e, exc_info=True)
            return PipelineResult(success=False, error_message=str(e))

    def cancel(self) -> None:
        """Signal the pipeline to cancel."""
        self.cancel_flag.set()
        self.status = PipelineStatus.CANCELLED
        logger.info("Pipeline cancellation requested: job=%s", self.job_id)

    def _check_cancelled(self) -> None:
        """Check if cancellation was requested."""
        if self.cancel_flag.is_set():
            raise asyncio.CancelledError("Pipeline cancelled")

    async def _report_progress(
        self,
        stage: PipelineStage,
        message: str,
        progress: float,
        current_short: int = 0,
        total_shorts: int = 1,
    ) -> None:
        """Report progress via callback."""
        self.current_stage = stage
        self.progress = progress

        elapsed = time.monotonic()

        if self.progress_callback:
            progress_obj = PipelineProgress(
                stage=stage,
                stage_name=stage.name.replace("_", " ").title(),
                progress=progress,
                message=message,
                elapsed_time=elapsed,
                current_short=current_short,
                total_shorts=total_shorts,
            )
            try:
                await self.progress_callback(progress_obj)
            except Exception as e:
                logger.warning("Progress callback error: %s", e)

    # -----------------------------------------------------------------------
    # Pipeline Steps
    # -----------------------------------------------------------------------

    async def _step_download(self) -> Path:
        """Download video from URL or validate uploaded file."""
        from video_processing.downloader import download_video

        if self.config.source_file and self.config.source_file.exists():
            # Use uploaded file
            dest = self.temp_dir / self.config.source_file.name
            if dest != self.config.source_file:
                import shutil
                shutil.copy2(self.config.source_file, dest)
            logger.info("Using uploaded file: %s", dest.name)
            return dest

        if self.config.source_url:
            # Download from URL
            result = await download_video(
                url=self.config.source_url,
                output_dir=self.temp_dir,
                quality="1080p",
            )
            logger.info("Downloaded: %s", result.path.name)
            return result.path

        raise ValueError("No source URL or file provided")

    async def _step_extract_audio(self, video_path: Path) -> Path:
        """Extract audio from video with normalization."""
        from transcription.extractor import extract_audio

        output_path = await extract_audio(
            video_path=str(video_path),
            output_dir=self.temp_dir,
            normalize=True,
            sample_rate=16000,
        )
        logger.info("Audio extracted: %s", output_path.name)
        return output_path

    async def _step_transcribe(self, audio_path: Path) -> dict:
        """Transcribe audio using Groq Whisper."""
        from transcription.whisper import transcribe_audio

        result = await transcribe_audio(
            audio_path=str(audio_path),
            language=self.config.language,
        )

        self._transcript = {
            "text": result["text"],
            "language": result["language"],
            "words": result.get("words", []),
            "segments": result.get("segments", []),
        }

        logger.info(
            "Transcription complete: %d chars, %d words, %d segments",
            len(result["text"]),
            len(result.get("words", [])),
            len(result.get("segments", [])),
        )
        return self._transcript

    async def _step_detect_viral(self, transcript: dict) -> list[dict]:
        """Detect viral moments in the transcript."""
        from ai.viral_detector import detect_viral_moments

        text = transcript["text"]
        mode = self.config.viral_detection_mode

        moments = await detect_viral_moments(
            transcript=text,
            num_moments=self.config.num_shorts * 2,  # Get extras for selection
            mode=mode,
            max_duration=MAX_SHORTS_DURATION_SECONDS,
        )

        logger.info("Detected %d viral moments", len(moments))
        return moments

    async def _step_generate_titles(self, transcript: dict) -> dict:
        """Generate viral titles, descriptions, and hashtags."""
        from ai.title_generator import generate_viral_metadata

        text = transcript["text"]
        result = await generate_viral_metadata(transcript=text)

        logger.info("Generated titles: %s", result.get("titles", []))
        return result

    async def _process_single_short(self, index: int, total: int) -> Path:
        """
        Process a single viral short from clip to final output.

        Orchestrates: clip → reframe → captions → emoji → zoom → B-roll → render
        """
        short_dir = self.temp_dir / f"short_{index + 1}"
        short_dir.mkdir(parents=True, exist_ok=True)

        # Get the viral moment for this short
        if self._viral_moments and index < len(self._viral_moments):
            moment = self._viral_moments[index]
        else:
            # Fallback: divide video evenly
            from ffmpeg_utils.commands import get_video_duration
            duration = await get_video_duration(self._video_path)
            duration = duration or 60.0
            seg_duration = duration / max(total, 1)
            moment = {
                "start": index * seg_duration,
                "end": (index + 1) * seg_duration,
                "score": 0.5,
                "reason": "Fallback segment",
            }

        # Clip the video
        await self._report_progress(PipelineStage.CLIP, f"Clipping short {index + 1}...", 0.55)
        clip_path = await self._clip_video(moment, short_dir)

        # Auto-reframe to 9:16
        await self._report_progress(PipelineStage.REFRAME, f"Auto-reframing short {index + 1}...", 0.6)
        reframed_path = await self._reframe_video(clip_path, short_dir)

        # Generate captions
        if self._transcript:
            await self._report_progress(PipelineStage.CAPTIONS, f"Adding captions to short {index + 1}...", 0.7)
            caption_frames = await self._generate_captions(
                self._transcript, moment, reframed_path, short_dir,
            )
        else:
            caption_frames = None

        # Add emoji overlays
        await self._report_progress(PipelineStage.EMOJI, f"Adding emojis to short {index + 1}...", 0.75)
        emoji_data = await self._add_emojis(self._transcript, moment) if self.config.emoji_enabled else []

        # Apply zoom effects
        await self._report_progress(PipelineStage.ZOOM, f"Adding zoom to short {index + 1}...", 0.8)
        zoom_data = []
        if self.config.zoom_enabled:
            zoom_data = await self._apply_zoom(clip_path, moment)

        # Add B-roll
        await self._report_progress(PipelineStage.BROLL, f"Adding B-roll to short {index + 1}...", 0.85)
        broll_data = []
        if self.config.broll_enabled and self._transcript:
            broll_data = await self._add_broll(
                moment, self._transcript["text"], short_dir,
            )

        # Render final output
        await self._report_progress(PipelineStage.RENDER, f"Rendering short {index + 1}...", 0.9)
        output_path = await self._render_output(
            reframed_path, caption_frames, emoji_data, broll_data,
            zoom_data, short_dir, index,
        )

        return output_path

    async def _clip_video(self, moment: dict, output_dir: Path) -> Path:
        """Clip video at the viral moment timestamps."""
        from video_processing.clipping import clip_video

        start = moment.get("start", 0)
        end = moment.get("end", start + MAX_SHORTS_DURATION_SECONDS)

        # Ensure we don't exceed max duration
        end = min(end, start + MAX_SHORTS_DURATION_SECONDS)

        output_path = output_dir / "clip.mp4"

        result = await clip_video(
            input_path=str(self._video_path),
            start_time=start,
            end_time=end,
            output_path=str(output_path),
            remove_silence=self.config.silence_removal,
        )

        return Path(result) if isinstance(result, str) else output_path

    async def _reframe_video(self, clip_path: Path, output_dir: Path) -> Path:
        """Auto-reframe clip to 9:16 using face tracking."""
        from video_processing.reframe import reframe_video

        output_path = output_dir / "reframed.mp4"

        result = await reframe_video(
            input_path=str(clip_path),
            output_path=str(output_path),
            target_aspect="9:16",
            track_face=True,
        )

        return Path(result) if isinstance(result, str) else output_path

    async def _generate_captions(
        self,
        transcript: dict,
        moment: dict,
        video_path: Path,
        output_dir: Path,
    ) -> Optional[list[Path]]:
        """Generate animated caption frames."""
        from captions.generator import generate_caption_frames
        from ffmpeg_utils.commands import get_video_duration

        # Filter words to those within the clip's time range
        start_time = moment.get("start", 0)
        end_time = moment.get("end", start_time + 60)

        words = [
            w for w in transcript.get("words", [])
            if start_time <= w.get("start", 0) <= end_time
        ]

        if not words:
            return None

        # Normalize word timestamps to clip-relative
        for w in words:
            w["start"] = w.get("start", 0) - start_time
            w["end"] = w.get("end", 0) - start_time

        duration = await get_video_duration(video_path) or 60.0

        frames = await generate_caption_frames(
            words=words,
            style=self.config.caption_style,
            text_color=self.config.caption_color,
            output_dir=output_dir / "captions",
            duration=duration,
        )

        return frames

    async def _add_emojis(self, transcript: dict, moment: dict) -> list[dict]:
        """Generate emoji overlays based on transcript context."""
        from ai.emoji_engine import generate_emoji_overlays

        text = transcript["text"] if transcript else ""
        start_time = moment.get("start", 0)

        emojis = await generate_emoji_overlays(text=text)

        # Filter to moment's time range
        moment_emojis = [
            e for e in emojis
            if moment.get("start", 0) <= e.get("time", 0) <= moment.get("end", 999)
        ]

        return moment_emojis

    async def _apply_zoom(self, video_path: Path, moment: dict) -> list[tuple[float, float]]:
        """Apply zoom effects based on motion analysis."""
        from opencv_utils.motion_detector import get_zoom_points

        start_time = moment.get("start", 0)
        end_time = moment.get("end", start_time + 60)
        duration = end_time - start_time

        zoom_points = await get_zoom_points(
            video_path=video_path,
            video_duration=duration,
            intensity_threshold=0.35,
            min_spacing=3.0,
        )

        # Offset zoom times to clip-relative
        return [(zp[0] - start_time, zp[1]) for zp in zoom_points if zp[0] >= start_time]

    async def _add_broll(self, moment: dict, transcript: str, output_dir: Path) -> list[dict]:
        """Generate B-roll overlays."""
        from video_processing.broll import generate_broll

        start_time = moment.get("start", 0)
        end_time = moment.get("end", start_time + 60)
        duration = end_time - start_time

        broll_dirs = [Path(d) for d in BROLL_DIRS] if BROLL_DIRS else []

        placements = await generate_broll(
            video_duration=duration,
            broll_dirs=broll_dirs,
            transcript=transcript,
            num_clips=3,
        )

        return placements

    async def _render_output(
        self,
        video_path: Path,
        caption_frames: Optional[list[Path]],
        emoji_data: list[dict],
        broll_data: list[dict],
        zoom_data: list[tuple[float, float]],
        output_dir: Path,
        index: int,
    ) -> Path:
        """Render the final output video."""
        from video_processing.output import VideoOutputRenderer

        output_path = output_dir / f"short_{index + 1}_final.mp4"

        renderer = VideoOutputRenderer(output_dir=output_dir)

        captions_dir = None
        if caption_frames:
            captions_dir = output_dir / "captions"

        result = await renderer.render(
            video_path=video_path,
            output_path=output_path,
            captions_dir=captions_dir,
            emoji_overlays=emoji_data if emoji_data else None,
            broll_clips=broll_data if broll_data else None,
            zoom_enabled=bool(zoom_data),
            quality=self.config.output_quality,
        )

        return result.file_path


# ---------------------------------------------------------------------------
# Convenience Function
# ---------------------------------------------------------------------------

async def process_viral_short(
    source_url: Optional[str] = None,
    source_file: Optional[Path] = None,
    num_shorts: int = 1,
    caption_style: str = "hormozi",
    emoji_enabled: bool = True,
    zoom_enabled: bool = True,
    broll_enabled: bool = True,
    quality: str = "high",
    job_id: Optional[str] = None,
    progress_callback: Optional[Callable[[PipelineProgress], Awaitable[None]]] = None,
) -> PipelineResult:
    """
    Process a viral short from source to output (convenience function).

    Args:
        source_url: YouTube URL to download.
        source_file: Path to uploaded video file.
        num_shorts: Number of shorts to generate.
        caption_style: Caption style name.
        emoji_enabled: Whether to add emojis.
        zoom_enabled: Whether to apply zoom effects.
        broll_enabled: Whether to add B-roll overlays.
        quality: Output quality level.
        job_id: Unique job identifier.
        progress_callback: Async progress callback.

    Returns:
        PipelineResult with output files.
    """
    config = PipelineConfig(
        source_url=source_url,
        source_file=source_file,
        num_shorts=num_shorts,
        caption_style=caption_style,
        emoji_enabled=emoji_enabled,
        zoom_enabled=zoom_enabled,
        broll_enabled=broll_enabled,
        output_quality=quality,
    )

    processor = PipelineProcessor(
        config=config,
        job_id=job_id,
        progress_callback=progress_callback,
    )

    return await processor.run()
