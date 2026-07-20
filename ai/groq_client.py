"""
Groq API client for the Viral Shorts Bot.

Provides a unified async client for:
- Whisper transcription (via Groq's Whisper API)
- LLM inference (via Groq's OpenAI-compatible API)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

import aiohttp

from configuration.config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_LLM_MODEL,
    GROQ_WHISPER_MODEL,
)
from utilities.logging_config import get_logger

logger = get_logger("ai.groq_client")


class GroqClient:
    """
    Async Groq API client.

    Supports:
    - Speech-to-text (Whisper)
    - Text generation (LLM)
    - Automatic retries with exponential backoff
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        whisper_model: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key or GROQ_API_KEY
        self.base_url = (base_url or GROQ_BASE_URL).rstrip("/")
        self.whisper_model = whisper_model or GROQ_WHISPER_MODEL
        self.llm_model = llm_model or GROQ_LLM_MODEL
        self.max_retries = max_retries
        self.timeout = timeout

    # -----------------------------------------------------------------------
    # Transcription (Whisper)
    # -----------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
        response_format: str = "verbose_json",
    ) -> dict:
        """
        Transcribe an audio file using Groq's Whisper API.

        Args:
            audio_path: Path to the audio file.
            language: Language code (e.g. 'en'). None = auto-detect.
            response_format: 'json', 'text', 'srt', 'verbose_json'.

        Returns:
            dict with transcription results including word timestamps.
        """
        url = f"{self.base_url}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        data = aiohttp.FormData()
        data.add_field("file", open(audio_path, "rb"), filename="audio.wav")
        data.add_field("model", self.whisper_model)
        data.add_field("response_format", response_format)
        if language:
            data.add_field("language", language)
        data.add_field("temperature", "0")

        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=self.timeout * 3),
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            logger.info(
                                "Transcription complete (model=%s, file=%s)",
                                self.whisper_model, Path(audio_path).name,
                            )
                            return result
                        else:
                            error_text = await response.text()
                            logger.warning(
                                "Transcription attempt %d failed (status=%d): %s",
                                attempt + 1, response.status, error_text[:200],
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    "Transcription attempt %d error: %s",
                    attempt + 1, e,
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(
            f"Transcription failed after {self.max_retries} retries for {audio_path}"
        )

    # -----------------------------------------------------------------------
    # LLM Inference
    # -----------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Generate a chat completion using Groq's LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            model: Model name (defaults to configured LLM model).
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            response_format: Optional response format (e.g. {"type": "json_object"}).

        Returns:
            The generated text content.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model or self.llm_model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            content = data["choices"][0]["message"]["content"]
                            logger.debug(
                                "LLM response (model=%s, tokens=%d)",
                                model or self.llm_model,
                                data["usage"]["completion_tokens"],
                            )
                            return content
                        else:
                            error_text = await response.text()
                            logger.warning(
                                "LLM attempt %d failed (status=%d): %s",
                                attempt + 1, response.status, error_text[:200],
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    "LLM attempt %d error: %s",
                    attempt + 1, e,
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(
            f"LLM completion failed after {self.max_retries} retries"
        )

    async def chat_completion_json(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> dict:
        """
        Generate a JSON response using Groq's LLM.

        Returns the parsed JSON dict.
        """
        response = await self.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON response: %s", e)
            logger.debug("Raw response: %s", response[:500])
            raise ValueError(f"LLM returned invalid JSON: {e}")

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """List available models on the Groq API."""
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                data = await response.json()
                return data.get("data", [])


# Singleton instance
groq_client = GroqClient()
