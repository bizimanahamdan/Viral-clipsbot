"""
AI Title Generator — Groq LLM integration.

Generates viral titles, descriptions, hashtags, hooks,
and pinned comment suggestions for each short video.

Uses Groq's LLM with carefully engineered prompts to produce
high-performing titles optimised for short-form platforms.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from ai.groq_client import groq_client
from utilities.logging_config import get_logger

logger = get_logger("ai.title_generator")


@dataclass
class GeneratedTitle:
    """A generated viral title for a short."""
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    hook: str = ""
    pinned_comment: str = ""
    virality_score: float = 0.0


@dataclass
class TitleGenerationResult:
    """Result of title generation for a short."""
    titles: list[GeneratedTitle] = field(default_factory=list)
    best_title: Optional[GeneratedTitle] = None
    model_used: str = ""


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

TITLE_GENERATION_SYSTEM_PROMPT = """You are an expert viral content strategist. Your job is to create high-performing titles, descriptions, and hashtags for short-form video content (YouTube Shorts, TikTok, Instagram Reels).

Your titles should:
- Be attention-grabbing and curiosity-inducing
- Use power words and emotional triggers
- Be concise (under 60 characters for best performance)
- Create a curiosity gap that makes viewers click
- Be relevant to the content

Your descriptions should:
- Provide context without giving away the payoff
- Include a call-to-action
- Be 1-2 sentences

Your hashtags should:
- Mix broad and niche hashtags
- Include 5-10 relevant tags
- Not include generic tags like #fyp

Your hooks should:
- Be the first line viewers see/hear
- Create immediate curiosity
- Be under 15 words

Your pinned comment should:
- Ask an engaging question
- Encourage comments and interaction
- Be 1-2 sentences

Respond ONLY with valid JSON in this exact format:
{
  "titles": [
    {
      "title": "This Title Here",
      "description": "A compelling description...",
      "hashtags": ["#hashtag1", "#hashtag2"],
      "hook": "A hook that makes you want to watch...",
      "pinned_comment": "What do you think about...",
      "virality_score": 0.85
    }
  ]
}

Generate exactly {num_titles} different title options with varying angles."""

TITLE_GENERATION_USER_PROMPT = """Generate {num_titles} viral title options for this short video segment.

Transcript snippet:
{transcript_snippet}

Additional context about the source video:
{context}

Focus on making each title unique with a different angle:
1. Curiosity/mystery angle
2. Shock/surprise angle
3. Educational/value angle"""


async def generate_titles(
    transcript_snippet: str,
    context: str = "",
    num_titles: int = 3,
) -> TitleGenerationResult:
    """
    Generate viral titles for a short video segment using Groq LLM.

    Args:
        transcript_snippet: The transcript text for this segment.
        context: Additional context about the source video.
        num_titles: Number of title options to generate.

    Returns:
        TitleGenerationResult with generated titles.
    """
    logger.info(
        "Generating %d titles for segment (%d chars)",
        num_titles, len(transcript_snippet),
    )

    system_prompt = TITLE_GENERATION_SYSTEM_PROMPT.format(
        num_titles=num_titles,
    )
    user_prompt = TITLE_GENERATION_USER_PROMPT.format(
        num_titles=num_titles,
        transcript_snippet=transcript_snippet[:2000],  # Limit context length
        context=context[:1000] if context else "No additional context provided.",
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await groq_client.chat_completion_json(
            messages=messages,
            temperature=0.7,  # Higher temperature for creative variety
        )
    except Exception as e:
        logger.error("Title generation LLM call failed: %s", e)
        return TitleGenerationResult(
            titles=[],
            best_title=None,
            model_used="error",
        )

    # Parse the response
    raw_titles = response.get("titles", [])
    generated_titles = []

    for raw in raw_titles:
        title = GeneratedTitle(
            title=raw.get("title", "").strip(),
            description=raw.get("description", "").strip(),
            hashtags=raw.get("hashtags", []),
            hook=raw.get("hook", "").strip(),
            pinned_comment=raw.get("pinned_comment", "").strip(),
            virality_score=float(raw.get("virality_score", 0.0)),
        )
        # Clean up hashtags
        title.hashtags = [h if h.startswith("#") else f"#{h}" for h in title.hashtags]
        generated_titles.append(title)

    # Select best title
    best_title = max(generated_titles, key=lambda t: t.virality_score) if generated_titles else None

    result = TitleGenerationResult(
        titles=generated_titles,
        best_title=best_title,
        model_used="groq-llm",
    )

    logger.info(
        "Title generation complete: %d titles generated, best score=%.2f",
        len(generated_titles),
        best_title.virality_score if best_title else 0,
    )
    return result


async def generate_hashtags(
    topic: str,
    niche: str = "general",
    count: int = 10,
) -> list[str]:
    """
    Generate relevant hashtags for a short video using Groq LLM.

    Args:
        topic: The main topic/subject of the video.
        niche: The content niche (e.g. 'tech', 'finance', 'entertainment').
        count: Number of hashtags to generate.

    Returns:
        List of hashtag strings.
    """
    system_prompt = f"""You are a social media hashtag expert. Generate exactly {count} highly relevant hashtags for short-form video content.

Rules:
- Each hashtag must be relevant to the content
- Mix trending and niche-specific tags
- No spaces in hashtags
- Do NOT include #fyp, #foryou, #viral (too generic)
- Return ONLY a JSON array of strings
"""

    user_prompt = f"""Topic: {topic}
Niche: {niche}

Generate {count} hashtags:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await groq_client.chat_completion_json(
            messages=messages,
            temperature=0.5,
        )
        # The response might be a list directly or have a key
        if isinstance(response, list):
            hashtags = [str(h) for h in response]
        elif isinstance(response, dict):
            hashtags = list(response.values()) if response else []
            # Try common keys
            for key in ["hashtags", "tags", "items", "results"]:
                if key in response and isinstance(response[key], list):
                    hashtags = response[key]
                    break
        else:
            hashtags = []

        # Clean up
        hashtags = [
            h if h.startswith("#") else f"#{h}"
            for h in hashtags[:count]
            if isinstance(h, str) and h.strip()
        ]

        logger.info("Generated %d hashtags for topic: %s", len(hashtags), topic[:50])
        return hashtags

    except Exception as e:
        logger.error("Hashtag generation failed: %s", e)
        return []


async def generate_hook(
    transcript_snippet: str,
    style: str = "question",
) -> str:
    """
    Generate a compelling hook for a short video using Groq LLM.

    Args:
        transcript_snippet: The transcript text for the segment.
        style: Hook style ('question', 'statement', 'shock', 'story').

    Returns:
        A compelling hook string.
    """
    style_instructions = {
        "question": "Ask a provocative question that makes viewers curious",
        "statement": "Make a bold, controversial statement",
        "shock": "Lead with something shocking or unbelievable",
        "story": "Start a story that viewers need to hear the end of",
    }

    instruction = style_instructions.get(style, style_instructions["question"])

    system_prompt = """You are an expert at writing hooks for short-form video content. Your hooks should be:
- Under 15 words
- Immediately attention-grabbing
- Create a curiosity gap
- Make viewers NEED to watch the rest

""" + instruction

    user_prompt = f"""Based on this transcript snippet, write ONE compelling hook:

{transcript_snippet[:1500]}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = await groq_client.chat_completion(
            messages=messages,
            temperature=0.6,
            max_tokens=50,
        )
        hook = result.strip().strip('"').strip("'")
        logger.info("Generated hook: %s", hook[:80])
        return hook
    except Exception as e:
        logger.error("Hook generation failed: %s", e)
        return ""


async def generate_pinned_comment(
    title: str,
    transcript_snippet: str,
) -> str:
    """
    Generate a suggested pinned comment for engagement.

    Args:
        title: The video title.
        transcript_snippet: The transcript text for the segment.

    Returns:
        A suggested pinned comment string.
    """
    system_prompt = """You are an engagement expert for short-form video content. Write a pinned comment that:
- Asks an engaging question
- Encourages viewers to comment
- Relates to the video content
- Is 1-2 sentences maximum
- Feels natural and conversational

Write ONE pinned comment."""

    user_prompt = f"""Title: {title}
Content: {transcript_snippet[:1000]}

Write a pinned comment for this video:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = await groq_client.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=80,
        )
        comment = result.strip().strip('"').strip("'")
        logger.info("Generated pinned comment: %s", comment[:80])
        return comment
    except Exception as e:
        logger.error("Pinned comment generation failed: %s", e)
        return ""
