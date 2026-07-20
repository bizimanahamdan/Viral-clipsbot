"""
Viral moment detector — Groq LLM integration.

Analyses transcripts to detect the most engaging moments based on:
- Hook strength
- Emotional moments
- Funny moments
- Storytelling arcs
- High-energy sections
- Audience retention likelihood
- Curiosity triggers
- Conflict/tension
- Educational value
- Surprise elements

Uses Groq's LLM to score and rank transcript segments.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from ai.groq_client import groq_client
from configuration.config import MIN_SHORTS_DURATION_SECONDS, MAX_SHORTS_DURATION_SECONDS
from utilities.logging_config import get_logger

logger = get_logger("ai.viral_detector")


@dataclass
class ViralMoment:
    """Represents a detected viral moment in a video."""
    start_time: float
    end_time: float
    score: float
    hook_strength: float
    emotional_intensity: float
    humor_score: float
    storytelling_quality: float
    energy_level: float
    retention_likelihood: float
    curiosity_score: float
    conflict_score: float
    educational_value: float
    surprise_score: float
    transcript_snippet: str
    reason: str


@dataclass
class DetectionResult:
    """Result of viral moment detection on a video."""
    moments: list[ViralMoment] = field(default_factory=list)
    total_score: float = 0.0
    model_used: str = ""


# ---------------------------------------------------------------------------
# LLM Prompt Engineering
# ---------------------------------------------------------------------------

VIRAL_DETECTION_SYSTEM_PROMPT = """You are an expert viral content analyst. Your job is to analyse video transcripts and identify the most viral, engaging moments that would perform well as short-form content (YouTube Shorts, TikTok, Instagram Reels).

You score each moment on these 10 dimensions (each 0.0-1.0):
1. hook_strength — Does it grab attention in the first 3 seconds?
2. emotional_intensity — Does it evoke strong emotions?
3. humor_score — Is it funny or entertaining?
4. storytelling_quality — Does it tell a compelling story?
5. energy_level — Is the delivery energetic and dynamic?
6. retention_likelihood — Will viewers watch until the end?
7. curiosity_score — Does it create a curiosity gap?
8. conflict_score — Is there tension or controversy?
9. educational_value — Does it teach something valuable?
10. surprise_score — Is there an unexpected twist or revelation?

For each moment, also provide a brief reason explaining WHY it would go viral.

Respond ONLY with valid JSON in this exact format:
{
  "moments": [
    {
      "start_time": 0.0,
      "end_time": 58.5,
      "hook_strength": 0.9,
      "emotional_intensity": 0.8,
      "humor_score": 0.3,
      "storytelling_quality": 0.95,
      "energy_level": 0.7,
      "retention_likelihood": 0.85,
      "curiosity_score": 0.8,
      "conflict_score": 0.4,
      "educational_value": 0.7,
      "surprise_score": 0.6,
      "reason": "This moment opens with a shocking claim..."
    }
  ]
}

Rules:
- Each clip should be between {min_dur} and {max_dur} seconds
- Do NOT overlap moments
- Prefer moments with high scores across multiple dimensions
- Include the actual transcript text snippet for each moment
- Return exactly {num_moments} moments sorted by overall score (highest first)
- The overall score is the weighted average of all dimensions
"""

VIRAL_DETECTION_USER_PROMPT = """Here is the transcript of a video. Analyse it and find the {num_moments} most viral moments.

Transcript with timestamps:
{transcript}

Find the best moments for short-form content."""


def _build_segment_transcript(
    word_timestamps: list[dict],
    segment_size: float = 30.0,
    overlap: float = 10.0,
) -> str:
    """
    Build a readable transcript string with timestamps for the LLM.

    Groups words into segments of approximately `segment_size` seconds
    with `overlap` seconds of overlap between segments.
    """
    if not word_timestamps:
        return ""

    segments = []
    seg_start = 0.0

    while seg_start < word_timestamps[-1].get("end", 0):
        seg_words = []
        for w in word_timestamps:
            if seg_start <= w.get("start", 0) < seg_start + segment_size:
                seg_words.append(w)

        if seg_words:
            start_t = seg_words[0].get("start", seg_start)
            end_t = seg_words[-1].get("end", start_t + segment_size)
            text = " ".join(w["word"] for w in seg_words)
            segments.append(f"[{start_t:.1f}s - {end_t:.1f}s] {text}")

        seg_start += segment_size - overlap

    return "\n".join(segments)


def _calculate_composite_score(moment: dict) -> float:
    """
    Calculate the weighted composite viral score for a moment.

    Weights are tuned based on what drives short-form virality.
    """
    weights = {
        "hook_strength": 0.18,
        "emotional_intensity": 0.14,
        "humor_score": 0.08,
        "storytelling_quality": 0.12,
        "energy_level": 0.10,
        "retention_likelihood": 0.16,
        "curiosity_score": 0.10,
        "conflict_score": 0.06,
        "educational_value": 0.04,
        "surprise_score": 0.02,
    }

    total = 0.0
    for attr, weight in weights.items():
        value = moment.get(attr, 0.0)
        # Clamp to 0-1
        value = max(0.0, min(1.0, float(value)))
        total += value * weight

    return round(min(total, 1.0), 4)


def _extract_transcript_snippet(
    word_timestamps: list[dict],
    start: float,
    end: float,
) -> str:
    """Extract the transcript text for a given time range."""
    words = []
    for w in word_timestamps:
        w_start = w.get("start", 0)
        if start <= w_start < end:
            words.append(w["word"])
    return " ".join(words)


async def detect_viral_moments(
    transcript: str,
    word_timestamps: list[dict],
    num_moments: int = 3,
    mode: str = "top_3",
) -> DetectionResult:
    """
    Analyse a transcript and detect the most viral moments using Groq LLM.

    Args:
        transcript: Full transcript text.
        word_timestamps: List of dicts with 'word', 'start', 'end', 'confidence'.
        num_moments: Number of moments to detect (1-10).
        mode: Detection mode ('top_3', 'top_5', 'top_10', 'custom').

    Returns:
        DetectionResult with scored viral moments.
    """
    # Determine actual number of moments
    mode_counts = {"top_3": 3, "top_5": 5, "top_10": 10}
    if mode in mode_counts:
        num_moments = mode_counts[mode]
    num_moments = max(1, min(num_moments, 10))

    logger.info(
        "Detecting viral moments: mode=%s, count=%d, transcript_length=%d chars",
        mode, num_moments, len(transcript),
    )

    # Build the timestamped transcript for the LLM
    segment_text = _build_segment_transcript(
        word_timestamps,
        segment_size=60.0,
        overlap=15.0,
    )

    # Build prompts
    system_prompt = VIRAL_DETECTION_SYSTEM_PROMPT.format(
        min_dur=MIN_SHORTS_DURATION_SECONDS,
        max_dur=MAX_SHORTS_DURATION_SECONDS,
        num_moments=num_moments,
    )
    user_prompt = VIRAL_DETECTION_USER_PROMPT.format(
        num_moments=num_moments,
        transcript=segment_text,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Call Groq LLM
    try:
        response = await groq_client.chat_completion_json(
            messages=messages,
            temperature=0.4,  # Lower temperature for consistent scoring
        )
    except Exception as e:
        logger.error("Viral detection LLM call failed: %s", e)
        return DetectionResult(moments=[], total_score=0.0, model_used="error")

    # Parse the response
    raw_moments = response.get("moments", [])
    parsed_moments = []
    total_score = 0.0

    for raw in raw_moments:
        score = _calculate_composite_score(raw)
        start = float(raw.get("start_time", 0))
        end = float(raw.get("end_time", start + 30))

        # Clamp to valid bounds
        end = min(end, start + MAX_SHORTS_DURATION_SECONDS)
        end = max(end, start + MIN_SHORTS_DURATION_SECONDS)

        # Extract transcript snippet
        snippet = raw.get("transcript_snippet", "")
        if not snippet:
            snippet = _extract_transcript_snippet(word_timestamps, start, end)

        moment = ViralMoment(
            start_time=start,
            end_time=end,
            score=score,
            hook_strength=float(raw.get("hook_strength", 0)),
            emotional_intensity=float(raw.get("emotional_intensity", 0)),
            humor_score=float(raw.get("humor_score", 0)),
            storytelling_quality=float(raw.get("storytelling_quality", 0)),
            energy_level=float(raw.get("energy_level", 0)),
            retention_likelihood=float(raw.get("retention_likelihood", 0)),
            curiosity_score=float(raw.get("curiosity_score", 0)),
            conflict_score=float(raw.get("conflict_score", 0)),
            educational_value=float(raw.get("educational_value", 0)),
            surprise_score=float(raw.get("surprise_score", 0)),
            transcript_snippet=snippet,
            reason=raw.get("reason", ""),
        )
        parsed_moments.append(moment)
        total_score += score

    # Sort by composite score descending
    parsed_moments.sort(key=lambda m: m.score, reverse=True)

    # Ensure non-overlapping moments (remove overlaps, prefer higher score)
    parsed_moments = _remove_overlaps(parsed_moments)

    result = DetectionResult(
        moments=parsed_moments[:num_moments],
        total_score=round(total_score / max(len(parsed_moments), 1), 4),
        model_used="groq-llm",
    )

    logger.info(
        "Viral detection complete: %d moments found, avg score=%.3f",
        len(result.moments), result.total_score,
    )
    return result


def _remove_overlaps(moments: list[ViralMoment]) -> list[ViralMoment]:
    """
    Remove overlapping moments, keeping higher-scored ones.

    Args:
        moments: List of moments sorted by score (highest first).

    Returns:
        Non-overlapping list of moments.
    """
    if not moments:
        return []

    # Sort by score descending
    moments.sort(key=lambda m: m.score, reverse=True)

    kept = []
    for moment in moments:
        overlaps = False
        for kept_moment in kept:
            if moment.start_time < kept_moment.end_time and moment.end_time > kept_moment.start_time:
                overlaps = True
                break
        if not overlaps:
            kept.append(moment)

    # Re-sort by start time
    kept.sort(key=lambda m: m.start_time)
    return kept


async def generate_viral_score(
    transcript: str,
    moment: ViralMoment,
) -> float:
    """
    Generate a refined viral score for a single moment using the LLM.

    Uses the LLM to double-check the scoring if needed.
    """
    # The composite score from _calculate_composite_score is already good,
    # but we can refine it with additional LLM analysis if desired.
    # For now, return the weighted composite score.
    score = moment.score

    # Apply a small boost if the snippet contains strong emotional words
    emotional_words = [
        "shocking", "unbelievable", "insane", "crazy", "amazing",
        "mind-blowing", "never", "secret", "truth", "warning",
    ]
    snippet_lower = moment.transcript_snippet.lower()
    boost = sum(1 for w in emotional_words if w in snippet_lower) * 0.02

    return min(score + boost, 1.0)
