"""
Audio Extractor — Full FFmpeg-based audio extraction pipeline.

Extracts audio from video files with:
- Volume normalisation (LUFS-based)
- Noise reduction via highpass/lowpass/denoise filters
- Chunk splitting for long-form Whisper transcription
- Format conversion to optimal 16kHz mono WAV
- Duration detection and audio metadata retrieval
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from configuration.config import TEMP_DIR, AUDIO_CHUNK_SIZE_SECONDS, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS
from utilities.logging_config import get_logger

logger = get_logger("transcription.extractor")


class AudioExtractor:
    """
    Full-featured audio extractor with normalisation, noise reduction,
    and chunk splitting capabilities.
    """

    def __init__(self, temp_dir: Optional[Path] = None):
        """
        Initialize the audio extractor.

        Args:
            temp_dir: Temporary directory for intermediate files.
        """
        self.temp_dir = temp_dir or TEMP_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def extract_audio(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        sample_rate: int = AUDIO_SAMPLE_RATE,
        channels: int = AUDIO_CHANNELS,
    ) -> Path:
        """
        Extract audio track from a video file using FFmpeg.

        Converts to 16-bit PCM WAV at 16kHz mono — the optimal format
        for Groq Whisper API transcription.

        Args:
            video_path: Path to the source video file.
            output_path: Optional output path. Auto-generated if None.
            sample_rate: Output sample rate in Hz (16000 for Whisper).
            channels: Number of audio channels (1=mono for Whisper).

        Returns:
            Path to the extracted audio file.

        Raises:
            RuntimeError: If FFmpeg extraction fails.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{video_path.stem}_audio.wav"

        logger.info("Extracting audio from %s -> %s", video_path.name, output_path.name)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn",  # No video stream
            "-acodec", "pcm_s16le",  # 16-bit PCM (required by Whisper)
            "-ar", str(sample_rate),  # Sample rate
            "-ac", str(channels),  # Channels
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed for {video_path.name}: {stderr.decode(errors='replace')[:500]}"
            )

        logger.info("Audio extracted: %s (%s)", output_path, output_path.stat().st_size)
        return output_path

    async def normalise_audio(
        self,
        audio_path: Path,
        output_path: Optional[Path] = None,
        target_lufs: float = -16.0,
    ) -> Path:
        """
        Normalise audio volume using FFmpeg's loudnorm filter.

        Performs a single-pass loudness normalisation targeting the
        specified LUFS level. This ensures consistent volume across
        different source videos.

        Args:
            audio_path: Path to the input audio file.
            output_path: Optional output path.
            target_lufs: Target loudness in LUFS (-16 is broadcast standard).

        Returns:
            Path to the normalised audio file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{audio_path.stem}_normalised.wav"

        logger.info("Normalising audio to %.1f LUFS: %s", target_lufs, audio_path.name)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.warning("Loudness normalisation failed, using basic normalisation")
            # Fallback: basic normalisation
            cmd_fallback = [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-af", "loudnorm",
                str(output_path),
            ]
            process2 = await asyncio.create_subprocess_exec(
                *cmd_fallback,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr2 = await process2.communicate()
            if process2.returncode != 0:
                raise RuntimeError(f"Audio normalisation failed: {stderr2.decode(errors='replace')[:500]}")

        logger.info("Audio normalised: %s", output_path)
        return output_path

    async def remove_noise(
        self,
        audio_path: Path,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Reduce background noise using FFmpeg audio filters.

        Applies:
        - High-pass filter (80Hz) to remove low-frequency rumble
        - Low-pass filter (12kHz) to remove high-frequency hiss
        - Afftdn dynamic noise reduction

        Args:
            audio_path: Path to the input audio file.
            output_path: Optional output path.

        Returns:
            Path to the noise-reduced audio file.
        """
        if output_path is None:
            output_path = self.temp_dir / f"{audio_path.stem}_denoised.wav"

        logger.info("Removing noise from: %s", audio_path.name)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af",
            "highpass=f=80,"       # Remove sub-bass rumble
            "lowpass=f=12000,"     # Remove high-frequency hiss
            "afftdn=nr=80",        # Dynamic noise reduction
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.warning("Noise reduction failed, copying original: %s", stderr.decode(errors='replace')[:200])
            shutil.copy2(audio_path, output_path)
            return output_path

        logger.info("Noise removed: %s", output_path)
        return output_path

    async def split_into_chunks(
        self,
        audio_path: Path,
        chunk_duration: float = AUDIO_CHUNK_SIZE_SECONDS,
        overlap: float = 2.0,
    ) -> list[Path]:
        """
        Split audio into overlapping chunks for Whisper transcription.

        Overlapping chunks prevent sentence/word boundary issues and
        allow Whisper to maintain context across chunk boundaries.

        Args:
            audio_path: Path to the full audio file.
            chunk_duration: Duration of each chunk in seconds.
            overlap: Overlap between consecutive chunks in seconds.

        Returns:
            List of paths to chunk audio files.
        """
        duration = await self.get_audio_duration(audio_path)
        if duration is None or duration <= 0:
            raise RuntimeError(f"Cannot determine duration of {audio_path}")

        logger.info(
            "Splitting audio (%.1fs) into %.1fs chunks with %.1fs overlap: %s",
            duration, chunk_duration, overlap, audio_path.name,
        )

        chunks = []
        start = 0.0
        chunk_idx = 0

        while start < duration:
            chunk_path = self.temp_dir / f"{audio_path.stem}_chunk_{chunk_idx:03d}.wav"
            actual_duration = min(chunk_duration, duration - start)

            if actual_duration <= 0.5:  # Skip very short trailing chunks
                break

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(audio_path),
                "-t", str(actual_duration),
                "-c", "copy",
                str(chunk_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode == 0 and chunk_path.exists():
                chunks.append(chunk_path)
            else:
                # Fallback: re-encode the chunk
                cmd_reencode = [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", str(audio_path),
                    "-t", str(actual_duration),
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    str(chunk_path),
                ]
                process2 = await asyncio.create_subprocess_exec(
                    *cmd_reencode,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await process2.communicate()
                if process2.returncode == 0:
                    chunks.append(chunk_path)
                else:
                    logger.warning("Failed to create chunk %d at %.1fs", chunk_idx, start)

            chunk_idx += 1
            start += chunk_duration - overlap

        logger.info("Created %d audio chunks", len(chunks))
        return chunks

    async def get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """
        Get the duration of an audio/video file in seconds.

        Uses ffprobe for accurate duration detection.

        Args:
            audio_path: Path to the file.

        Returns:
            Duration in seconds, or None if it cannot be determined.
        """
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode == 0:
                info = json.loads(stdout.decode())
                return float(info["format"]["duration"])
        except (asyncio.TimeoutError, json.JSONDecodeError, KeyError) as e:
            logger.warning("Cannot get duration for %s: %s", audio_path.name, e)

        return None

    async def get_audio_info(self, audio_path: Path) -> dict:
        """
        Get detailed audio information from a file.

        Returns dict with keys: duration, sample_rate, channels, codec, bitrate.
        """
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(audio_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode == 0:
                info = json.loads(stdout.decode())
                audio_stream = None
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        audio_stream = stream
                        break

                fmt = info.get("format", {})
                return {
                    "duration": float(fmt.get("duration", 0)),
                    "sample_rate": int(audio_stream.get("sample_rate", 44100) if audio_stream else 44100),
                    "channels": int(audio_stream.get("channels", 1) if audio_stream else 1),
                    "codec": audio_stream.get("codec_name", "unknown") if audio_stream else "unknown",
                    "bitrate": int(fmt.get("bit_rate", 0)),
                }
        except Exception as e:
            logger.warning("Cannot get audio info for %s: %s", audio_path.name, e)

        return {
            "duration": 0,
            "sample_rate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "codec": "unknown",
            "bitrate": 0,
        }

    async def extract_and_process(
        self,
        video_path: Path,
        normalise: bool = True,
        denoise: bool = True,
        split_chunks: bool = True,
    ) -> dict:
        """
        Full audio extraction and processing pipeline.

        Orchestrates: extract -> normalise -> denoise -> chunk.

        Args:
            video_path: Path to the source video.
            normalise: Whether to normalise volume.
            denoise: Whether to remove background noise.
            split_chunks: Whether to split into chunks.

        Returns:
            Dict with keys: 'audio_path', 'chunks', 'duration', 'info'.
        """
        logger.info("Starting full audio pipeline for: %s", video_path.name)

        # Step 1: Extract audio
        audio_path = await self.extract_audio(video_path)

        # Step 2: Normalise
        if normalise:
            audio_path = await self.normalise_audio(audio_path)

        # Step 3: Denoise
        if denoise:
            audio_path = await self.remove_noise(audio_path)

        # Step 4: Get metadata
        info = await self.get_audio_info(audio_path)
        duration = info.get("duration", 0)

        # Step 5: Split into chunks if needed
        chunks = []
        if split_chunks and duration > AUDIO_CHUNK_SIZE_SECONDS:
            chunks = await self.split_into_chunks(audio_path)

        result = {
            "audio_path": audio_path,
            "chunks": chunks if chunks else [audio_path],
            "duration": duration,
            "info": info,
        }

        logger.info(
            "Audio pipeline complete: duration=%.1fs, chunks=%d",
            duration, len(result["chunks"]),
        )
        return result


# Module-level convenience functions for backward compatibility

async def extract_audio(
    video_path: str | Path,
    output_path: Optional[str | Path] = None,
    sample_rate: int = AUDIO_SAMPLE_RATE,
    channels: int = AUDIO_CHANNELS,
) -> Path:
    """Extract audio from a video file (convenience function)."""
    extractor = AudioExtractor()
    return await extractor.extract_audio(
        Path(video_path), Path(output_path) if output_path else None,
        sample_rate, channels,
    )


async def normalise_audio(
    audio_path: str | Path,
    output_path: Optional[str | Path] = None,
) -> Path:
    """Normalise audio volume (convenience function)."""
    extractor = AudioExtractor()
    return await extractor.normalise_audio(
        Path(audio_path), Path(output_path) if output_path else None,
    )


async def split_audio(
    audio_path: str | Path,
    chunk_duration: int = AUDIO_CHUNK_SIZE_SECONDS,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """Split audio into chunks (convenience function)."""
    extractor = AudioExtractor()
    extractor.temp_dir = output_dir or TEMP_DIR
    return await extractor.split_into_chunks(Path(audio_path), chunk_duration)
