"""
Emoji Engine — Context-aware emoji insertion for captions.

Analyses the semantic meaning of words and phrases in the transcript
to automatically insert relevant emojis. Avoids emoji spam by:
- Limiting total emojis per caption
- Prioritising the most contextually relevant emoji
- Spacing emojis across the caption naturally
- Supporting multiple language contexts
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from utilities.logging_config import get_logger

logger = get_logger("ai.emoji_engine")

# ---------------------------------------------------------------------------
# Emoji mapping by semantic category
# ---------------------------------------------------------------------------

EMOJI_MAP: dict[str, list[str]] = {
    # Money / Finance
    "money": ["💰", "💵", "💸", "🤑"],
    "cash": ["💵", "💲", "🤑"],
    "rich": ["💰", "🤑", "💎"],
    "dollar": ["💵", "💲", "💰"],
    "profit": ["📈", "💰", "🤑"],
    "income": ["💰", "📊", "💵"],
    "invest": ["📈", "💰", "🎯"],
    "business": ["💼", "📊", "🏢"],
    "stock": ["📈", "📊", "💹"],
    "crypto": ["₿", "🪙", "📈"],
    "bank": ["🏦", "💰", "💳"],
    "salary": ["💰", "💵", "📋"],
    "tax": ["📋", "💸", "😩"],
    "debt": ["😩", "💸", "⚠️"],

    # Fire / Hype
    "fire": ["🔥", "🔥🔥"],
    "hot": ["🔥", "🌡️"],
    "amazing": ["🔥", "✨", "🤯"],
    "incredible": ["🤯", "🔥", "✨"],
    "insane": ["🤯", "🔥", "😱"],
    "crazy": ["🤯", "😱", "🔥"],
    "lit": ["🔥", "🔥🔥"],
    "dope": ["🔥", "✨"],

    # Shock / Surprise
    "shock": ["😱", "🤯", "💥"],
    "surprised": ["😱", "🤯", "😲"],
    "unbelievable": ["😱", "🤯", "💥"],
    "mind blown": ["🤯", "💥", "🔥"],
    "wow": ["😮", "🤩", "✨"],
    "unreal": ["😱", "🤯", "✨"],
    "impossible": ["😱", "🚫", "🤯"],

    # Love / Positive
    "love": ["❤️", "💕", "🥰"],
    "beautiful": ["✨", "💖", "🌟"],
    "happy": ["😊", "😄", "🎉"],
    "great": ["👏", "✨", "💯"],
    "awesome": ["🙌", "✨", "💯"],
    "perfect": ["✨", "💯", "🎯"],
    "success": ["🏆", "✅", "🎉"],
    "win": ["🏆", "🥇", "💪"],

    # Laugh / Funny
    "funny": ["😂", "🤣", "😆"],
    "laugh": ["😂", "🤣", "😆"],
    "lol": ["😂", "🤣"],
    "hilarious": ["😂", "🤣", "💀"],
    "joke": ["😂", "🤣", "🃏"],
    "comedy": ["😂", "🎭", "🤣"],
    "meme": ["😂", "💀", "🤣"],
    "dead": ["💀", "😂"],

    # Sad / Negative
    "sad": ["😢", "😞", "💔"],
    "cry": ["😢", "😭", "💔"],
    "fail": ["😬", "💔", "❌"],
    "mistake": ["😬", "⚠️", "❌"],
    "wrong": ["❌", "⚠️", "🚫"],
    "bad": ["👎", "❌", "😬"],
    "terrible": ["😱", "💀", "🚫"],

    # Sports
    "sport": ["⚽", "🏀", "🏈", "🎾"],
    "football": ["⚽", "🏈"],
    "basketball": ["🏀", "🏆"],
    "game": ["🎮", "🕹️", "🏆"],
    "soccer": ["⚽", "🏟️"],
    "baseball": ["⚾"],
    "tennis": ["🎾", "🏆"],
    "boxing": ["🥊", "👊"],
    "fight": ["🥊", "👊", "💥"],
    "team": ["👥", "🤝", "🏆"],
    "champion": ["🏆", "🥇", "👑"],
    "medal": ["🥇", "🥈", "🥉"],

    # Technology
    "tech": ["💻", "🤖", "⚡"],
    "ai": ["🤖", "🧠", "⚡"],
    "robot": ["🤖", "⚙️"],
    "computer": ["💻", "🖥️"],
    "phone": ["📱", "📲"],
    "code": ["💻", "⌨️", "👨‍💻"],
    "hacker": ["👨‍💻", "💻", "🔒"],
    "internet": ["🌐", "💻", "📶"],
    "app": ["📱", "📲", "💻"],
    "software": ["💻", "⚙️", "🔧"],
    "data": ["📊", "📈", "💾"],
    "algorithm": ["🧠", "🤖", "📊"],
    "gpt": ["🤖", "🧠", "⚡"],
    "chatgpt": ["🤖", "💬", "🧠"],

    # Education
    "learn": ["📚", "🎓", "💡"],
    "teach": ["📚", "👨‍🏫", "💡"],
    "knowledge": ["📚", "🧠", "💡"],
    "smart": ["🧠", "💡", "📚"],
    "genius": ["🧠", "💡", "🎯"],
    "student": ["🎓", "📚", "👨‍🎓"],
    "school": ["🏫", "📚", "🎓"],
    "university": ["🎓", "🏛️", "📚"],
    "tip": ["💡", "📌", "✅"],
    "trick": ["💡", "🎯", "🔑"],
    "hack": ["💡", "🔧", "⚡"],
    "secret": ["🤫", "🔒", "👀"],
    "reveal": ["👀", "🔓", "💡"],

    # Food
    "food": ["🍕", "🍔", "🍜"],
    "eat": ["🍽️", "😋"],
    "cook": ["👨‍🍳", "🍳"],
    "recipe": ["📖", "🍳", "👨‍🍳"],
    "restaurant": ["🍽️", "⭐", "👨‍🍳"],
    "delicious": ["😋", "🤤", "👌"],
    "pizza": ["🍕"],
    "burger": ["🍔"],

    # Music
    "music": ["🎵", "🎶", "🎤"],
    "song": ["🎵", "🎶", "🎧"],
    "dance": ["💃", "🕺", "🎶"],
    "concert": ["🎤", "🎶", "🎵"],
    "rapper": ["🎤", "🎵", "🎧"],
    "album": ["💿", "🎵", "🎶"],

    # Fitness / Health
    "workout": ["💪", "🏋️", "🔥"],
    "gym": ["🏋️", "💪", "🔥"],
    "exercise": ["💪", "🏃", "🔥"],
    "health": ["❤️", "🏥", "🌿"],
    "weight": ["⚖️", "💪", "🔥"],
    "muscle": ["💪", "🏋️", "💪"],

    # Travel
    "travel": ["✈️", "🌍", "🗺️"],
    "trip": ["✈️", "🗺️", "🎒"],
    "vacation": ["🏖️", "✈️", "🌴"],
    "beach": ["🏖️", "🌊", "☀️"],
    "city": ["🏙️", "🌆", "🗼"],

    # General / Common
    "important": ["⚠️", "📌", "❗"],
    "warning": ["⚠️", "🚨", "❗"],
    "check": ["✅", "✔️"],
    "cross": ["❌", "🚫"],
    "star": ["⭐", "🌟", "✨"],
    "rocket": ["🚀", "🛸"],
    "brain": ["🧠", "💭"],
    "eye": ["👀", "👁️"],
    "time": ["⏰", "⏱️", "🕐"],
    "money bag": ["💰", "💵"],
    "chart": ["📈", "📊"],
    "target": ["🎯"],
    "key": ["🔑"],
    "lock": ["🔒", "🔐"],
    "unlock": ["🔓", "🔑"],
    "light": ["💡", "✨"],
    "power": ["⚡", "💪", "🔥"],
    "speed": ["⚡", "💨", "🚀"],
    "growth": ["📈", "🌱", "🚀"],
    "money growth": ["💰", "📈"],
    "expensive": ["💸", "💰", "🤑"],
    "cheap": ["💰", "🏷️"],
    "free": ["🆓", "💰"],
    "number": ["🔢", "📊"],
    "one": ["1️⃣", "☝️"],
    "two": ["2️⃣", "✌️"],
    "three": ["3️⃣", "🤟"],
    "first": ["1️⃣", "🥇"],
    "best": ["🏆", "👑", "💯"],
    "worst": ["👎", "💀", "❌"],
    "new": ["✨", "🆕", "🌟"],
    "old": ["🏛️", "📜"],
    "big": ["🔥", "💪", "🏆"],
    "small": ["🔬", "📏"],
    "fast": ["⚡", "💨", "🚀"],
    "slow": ["🐢", "⏳"],
    "strong": ["💪", "🏋️", "💪"],
    "weak": ["😔", "💔"],
    "rich man": ["🤑", "💰", "👑"],
    "poor": ["😢", "💸"],
    "truth": ["💯", "✅", "📢"],
    "lie": ["❌", "🤥", "🚫"],
    "story": ["📖", "📚", "👀"],
    "history": ["📜", "🏛️", "📖"],
    "future": ["🔮", "🚀", "🔭"],
    "dream": ["💭", "✨", "🌟"],
    "reality": ["🌍", "📺", "💯"],
    "idea": ["💡", "🧠", "💭"],
    "problem": ["😩", "⚠️", "🔧"],
    "solution": ["💡", "✅", "🔑"],
    "question": ["❓", "🤔", "💭"],
    "answer": ["✅", "💡", "🔑"],
    "danger": ["🚨", "⚠️", "💀"],
    "safe": ["✅", "🛡️", "🔒"],
    "risk": ["⚠️", "🎲", "💀"],
    "opportunity": ["🚀", "💡", "🎯"],
    "challenge": ["💪", "🏆", "⚡"],
    "motivation": ["💪", "🔥", "🚀"],
    "inspiration": ["✨", "🌟", "💡"],
    "hustle": ["💪", "🔥", "💰"],
    "grind": ["💪", "🔥", "⚡"],
    "quit": ["🚫", "❌", "⛔"],
    "never": ["🚫", "❌", "💪"],
    "always": ["✅", "💯", "🔄"],
    "stop": ["🛑", "⛔", "🚫"],
    "start": ["🚀", "▶️", "✨"],
    "end": ["🏁", "🔚", "✅"],
    "king": ["👑", "🏆"],
    "boss": ["👔", "💼", "👑"],
    "leader": ["👑", "🏆", "💪"],
    "follower": ["👥", "📱", "👀"],
    "audience": ["👥", "👀", "📺"],
    "views": ["👀", "📺", "📈"],
    "subscriber": ["🔔", "👤", "📺"],
    "like": ["👍", "❤️"],
    "comment": ["💬", "📝"],
    "share": ["📤", "🔗"],
    "subscribe": ["🔔", "👍", "📺"],
    "follow": ["👤", "➕", "📱"],
}


# ---------------------------------------------------------------------------
# Emoji insertion logic
# ---------------------------------------------------------------------------

def _find_best_emoji(word: str) -> Optional[str]:
    """
    Find the best matching emoji for a word.

    Checks for exact matches first, then substring matches,
    and returns the most specific emoji.
    """
    word_lower = word.lower().strip()
    if not word_lower or len(word_lower) < 2:
        return None

    # Exact match
    if word_lower in EMOJI_MAP:
        return EMOJI_MAP[word_lower][0]

    # Multi-word key matches
    for key, emojis in EMOJI_MAP.items():
        if word_lower == key:
            return emojis[0]

    # Substring match (prefer longer matches for specificity)
    best_match = None
    best_len = 0

    for key, emojis in EMOJI_MAP.items():
        if key in word_lower and len(key) > best_len:
            # Don't match very short substrings to avoid false positives
            if len(key) >= 3:
                best_match = emojis[0]
                best_len = len(key)

    return best_match


def _should_insert_emoji(
    word: str,
    prev_emoji_positions: list[int],
    word_position: int,
    min_distance: int = 4,
) -> bool:
    """
    Determine whether to insert an emoji for this word.

    Rules to prevent emoji spam:
    - Minimum distance between emojis
    - Don't insert for very short words
    - Don't insert for the first word (usually an article)
    """
    if word_position == 0:
        return False

    if len(word) < 3:
        return False

    # Check minimum distance from last emoji
    if prev_emoji_positions:
        last_pos = prev_emoji_positions[-1]
        if word_position - last_pos < min_distance:
            return False

    return True


async def add_emojis_to_text(
    text: str,
    max_emojis: int = 5,
    min_distance: int = 4,
) -> str:
    """
    Add contextually relevant emojis to caption text.

    Intelligently inserts emojis based on semantic meaning while
    avoiding emoji spam by enforcing minimum distance rules.

    Args:
        text: The caption text to enhance.
        max_emojis: Maximum number of emojis to add.
        min_distance: Minimum words between emojis.

    Returns:
        Text with emojis inserted at appropriate positions.
    """
    if not text or not text.strip():
        return text

    words = text.split()
    if len(words) <= min_distance:
        # Text too short for emoji insertion
        return text

    # Find candidate emoji positions
    candidates = []
    prev_emoji_pos = -1

    for i, word in enumerate(words):
        # Strip punctuation for matching
        clean_word = re.sub(r'[^\w\s]', '', word)
        emoji = _find_best_emoji(clean_word)

        if emoji and _should_insert_emoji(
            clean_word, [prev_emoji_pos] if prev_emoji_pos >= 0 else [],
            i, min_distance,
        ):
            candidates.append((i, emoji))
            prev_emoji_pos = i

        if len(candidates) >= max_emojis * 2:
            # Stop searching once we have enough candidates
            break

    # Select best candidates (prioritise strong semantic matches)
    # and ensure spacing
    selected = []
    for pos, emoji in candidates:
        if not selected or (pos - selected[-1][0]) >= min_distance:
            selected.append((pos, emoji))
        if len(selected) >= max_emojis:
            break

    if not selected:
        return text

    # Build the result with emojis inserted
    result_words = list(words)
    for pos, emoji in reversed(selected):
        result_words.insert(pos + 1, emoji)

    result = " ".join(result_words)
    return result


async def get_emoji_for_word(word: str) -> Optional[str]:
    """Return a relevant emoji for a given word, or None."""
    return _find_best_emoji(word)


async def get_emojis_for_topic(
    topic: str,
    count: int = 3,
) -> list[str]:
    """
    Get relevant emojis for a given topic.

    Args:
        topic: The topic or keyword.
        count: Number of emojis to return.

    Returns:
        List of relevant emoji strings.
    """
    topic_lower = topic.lower().strip()
    found = []

    for key, emojis in EMOJI_MAP.items():
        if key in topic_lower or topic_lower in key:
            found.extend(emojis)
            if len(found) >= count:
                break

    return found[:count]


async def batch_add_emojis(
    texts: list[str],
    max_emojis_per_text: int = 5,
) -> list[str]:
    """
    Add emojis to multiple text strings in batch.

    Args:
        texts: List of caption texts.
        max_emojis_per_text: Maximum emojis per text.

    Returns:
        List of texts with emojis added.
    """
    results = []
    for text in texts:
        result = await add_emojis_to_text(
            text,
            max_emojis=max_emojis_per_text,
        )
        results.append(result)
    return results
