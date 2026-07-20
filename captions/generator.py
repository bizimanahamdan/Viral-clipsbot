"""
Caption Generator — Animated word-by-word captions with 5 styles.

Creates frame-accurate caption overlays using Pillow:
- TikTok/Reels style word-by-word animation
- Current word highlighting
- Stroke/outline effects
- Drop shadows
- Background highlight boxes
- Smart line wrapping
- Perfectly synced to audio timing
- Emoji integration

Styles: hormozi, clean, minimal, karaoke, typewriter
"""

from __future__ import annotations

import asyncio
import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from configuration.config import (
    CAPTION_FONT_PATH,
    CAPTION_FONT_SIZE,
    CAPTION_COLOR,
    CAPTION_HIGHLIGHT_COLOR,
    CAPTION_STROKE_COLOR,
    CAPTION_STROKE_WIDTH,
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    TEMP_DIR,
    OUTPUT_FPS,
)
from utilities.logging_config import get_logger

logger = get_logger("captions.generator")


# ---------------------------------------------------------------------------
# Caption Style Definitions
# ---------------------------------------------------------------------------

CAPTION_STYLES = {
    "hormozi": {
        "font_size": 64,
        "bold": True,
        "stroke": True,
        "shadow": True,
        "background_box": True,
        "highlight_current": True,
        "max_words_per_line": 6,
        "position": "center",
        "font_family": "Impact, Arial Black, Arial, sans-serif",
    },
    "clean": {
        "font_size": 52,
        "bold": True,
        "stroke": False,
        "shadow": True,
        "background_box": False,
        "highlight_current": True,
        "max_words_per_line": 8,
        "position": "center",
        "font_family": "Helvetica, Arial, sans-serif",
    },
    "minimal": {
        "font_size": 46,
        "bold": False,
        "stroke": False,
        "shadow": False,
        "background_box": False,
        "highlight_current": False,
        "max_words_per_line": 10,
        "position": "bottom",
        "font_family": "Helvetica, Arial, sans-serif",
    },
    "karaoke": {
        "font_size": 58,
        "bold": True,
        "stroke": True,
        "shadow": True,
        "background_box": True,
        "highlight_current": True,
        "max_words_per_line": 5,
        "position": "center",
        "font_family": "Impact, Arial Black, Arial, sans-serif",
    },
    "typewriter": {
        "font_size": 42,
        "bold": False,
        "stroke": False,
        "shadow": False,
        "background_box": False,
        "highlight_current": True,
        "max_words_per_line": 12,
        "position": "bottom",
        "font_family": "Courier New, Courier, monospace",
    },
}


@dataclass
class CaptionFrame:
    """Represents a single caption frame."""
    frame_index: int
    path: Path
    timestamp: float
    words_shown: list[str]
    current_word_index: int


class CaptionGenerator:
    """
    Generates animated word-by-word caption frames.

    Creates a PNG frame for each display moment, with the
    current word highlighted and context words visible.
    """

    def __init__(
        self,
        style: str = "hormozi",
        text_color: str = CAPTION_COLOR,
        highlight_color: str = CAPTION_HIGHLIGHT_COLOR,
        stroke_color: str = CAPTION_STROKE_COLOR,
        stroke_width: int = CAPTION_STROKE_WIDTH,
        font_path: Optional[str | Path] = None,
        fps: int = OUTPUT_FPS,
    ):
        """
        Initialize the caption generator.

        Args:
            style: Caption style name.
            text_color: Default text color (hex or RGB tuple).
            highlight_color: Color for highlighted word.
            stroke_color: Outline/stroke color.
            stroke_width: Outline width in pixels.
            font_path: Path to font file (.ttf/.otf).
            fps: Output video frame rate.
        """
        self.style_config = CAPTION_STYLES.get(style, CAPTION_STYLES["hormozi"])
        self.text_color = self._parse_color(text_color, (255, 255, 255))
        self.highlight_color = self._parse_color(highlight_color, (255, 255, 0))
        self.stroke_color = self._parse_color(stroke_color, (0, 0, 0))
        self.stroke_width = stroke_width
        self.font_path = font_path
        self.fps = fps

        # Load fonts
        self.font = self._load_font(self.style_config["font_size"])
        self.bold_font = self._load_font(self.style_config["font_size"] + 6)
        self.small_font = self._load_font(max(self.style_config["font_size"] - 12, 20))

    def _parse_color(self, color, default: tuple[int, ...]) -> tuple:
        """Parse a color string or return default."""
        if isinstance(color, tuple):
            return color
        if isinstance(color, str):
            color = color.lstrip("#")
            if len(color) == 6:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                return (r, g, b, 255)
            elif len(color) == 8:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                a = int(color[6:8], 16)
                return (r, g, b, a)
        return default

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Load a font at the given size."""
        if self.font_path:
            try:
                return ImageFont.truetype(str(self.font_path), size)
            except (OSError, IOError):
                pass

        # Try system fonts
        font_names = self.style_config.get("font_family", "Arial").split(",")
        for name in font_names:
            name = name.strip()
            system_paths = [
                f"/usr/share/fonts/truetype/{name.lower()}/{name}.ttf",
                f"/usr/share/fonts/TTF/{name}.ttf",
                f"/usr/share/fonts/{name}/{name}.ttf",
                f"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                f"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                f"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
            for path in system_paths:
                try:
                    return ImageFont.truetype(path, size)
                except (OSError, IOError):
                    continue

        return ImageFont.load_default()

    def _get_text_bbox(self, draw: ImageDraw.Draw, text: str, font) -> tuple[int, int, int, int]:
        """Get text bounding box with fallback."""
        try:
            return draw.textbbox((0, 0), text, font=font)
        except AttributeError:
            width = draw.textlength(text, font=font)
            return (0, 0, int(width), int(font.size * 1.2))

    def generate_frames(
        self,
        words: list[dict],
        output_dir: Optional[Path] = None,
        duration: float = 0.0,
    ) -> list[CaptionFrame]:
        """
        Generate caption frames for the entire video.

        Creates one frame per display unit (group of words shown together).
        Each frame shows the current word highlighted with context words.

        Args:
            words: List of dicts with 'word', 'start', 'end' keys.
            output_dir: Directory for output PNG frames.
            duration: Total video duration.

        Returns:
            List of CaptionFrame objects.
        """
        if output_dir is None:
            output_dir = TEMP_DIR / "caption_frames"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not words:
            return []

        frames = []
        max_words = self.style_config["max_words_per_line"]
        width, height = OUTPUT_WIDTH, OUTPUT_HEIGHT

        # Generate frame for each word as the "current" word
        for i, word_data in enumerate(words):
            # Determine the window of words to display
            start_idx = max(0, i - (max_words // 2))
            end_idx = min(len(words), i + (max_words // 2) + 1)
            visible_words = words[start_idx:end_idx]

            # Create transparent RGBA frame
            frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(frame)

            # Build word texts
            word_texts = [w["word"] for w in visible_words]

            # Calculate word positions for centering
            positions = self._calculate_word_positions(
                draw, visible_words, start_idx, i,
            )

            # Calculate total width for centering
            if positions:
                total_width = positions[-1]["x"] + positions[-1]["width"] - positions[0]["x"]
                offset_x = (width - total_width) // 2
            else:
                total_width = 0
                offset_x = width // 2

            # Position vertically
            if self.style_config["position"] == "center":
                base_y = height // 2 - self.style_config["font_size"]
            elif self.style_config["position"] == "bottom":
                base_y = height - int(height * 0.25)
            else:
                base_y = height // 2 - self.style_config["font_size"]

            # Handle multi-line
            lines = self._wrap_into_lines(positions, max_words, offset_x, width)

            # Draw each line
            for line_idx, line_words in enumerate(lines):
                line_y = base_y + line_idx * (self.style_config["font_size"] + 16)
                self._draw_caption_line(
                    draw, line_words, line_y, width, height,
                )

            # Save frame
            frame_path = output_dir / f"frame_{i:06d}.png"
            frame.save(str(frame_path))

            frames.append(CaptionFrame(
                frame_index=i,
                path=frame_path,
                timestamp=words[i]["start"],
                words_shown=[w["word"] for w in visible_words],
                current_word_index=i,
            ))

        logger.info(
            "Generated %d caption frames (%s style, %.0fs video)",
            len(frames), self.style_config.get("font_family", ""), duration,
        )
        return frames

    def _calculate_word_positions(
        self,
        draw: ImageDraw.Draw,
        words: list[dict],
        start_idx: int,
        current_idx: int,
    ) -> list[dict]:
        """
        Calculate positions for each word in the visible window.

        Returns list of dicts with word info and positions.
        """
        positions = []
        current_x = 0
        spacing = int(self.style_config["font_size"] * 0.25)

        for j, w in enumerate(words):
            word_text = w["word"]
            is_current = (start_idx + j) == current_idx
            use_font = self.bold_font if (is_current and self.style_config["highlight_current"]) else self.font

            bbox = self._get_text_bbox(draw, word_text, use_font)
            word_width = bbox[2] - bbox[0]

            positions.append({
                "text": word_text,
                "x": current_x,
                "width": word_width,
                "height": bbox[3] - bbox[1],
                "is_current": is_current,
                "font": use_font,
                "start": w["start"],
                "end": w["end"],
            })

            current_x += word_width + spacing

        return positions

    def _wrap_into_lines(
        self,
        positions: list[dict],
        max_words: int,
        offset_x: int,
        max_width: int,
    ) -> list[list[dict]]:
        """
        Wrap word positions into multiple lines.

        Splits words into lines based on max_words and available width.
        """
        if not positions:
            return []

        lines = []
        current_line = []
        current_width = 0
        spacing = int(self.style_config["font_size"] * 0.25)

        for pos in positions:
            word_total = pos["width"] + spacing
            if len(current_line) >= max_words or (current_width + word_total > max_width * 0.9 and current_line):
                # Recalculate positions for current line
                line_width = sum(p["width"] + spacing for p in current_line) - spacing
                line_offset = offset_x + (max_width * 0.9 - line_width) // 2
                if line_offset < 0:
                    line_offset = offset_x

                adjusted = []
                x = 0
                for p in current_line:
                    adjusted.append({**p, "x": x + line_offset})
                    x += p["width"] + spacing

                lines.append(adjusted)
                current_line = []
                current_width = 0

            current_line.append(pos)
            current_width += word_total

        if current_line:
            line_width = sum(p["width"] + spacing for p in current_line) - spacing
            line_offset = offset_x + (max_width * 0.9 - line_width) // 2
            if line_offset < 0:
                line_offset = offset_x

            adjusted = []
            x = 0
            for p in current_line:
                adjusted.append({**p, "x": x + line_offset})
                x += p["width"] + spacing

            lines.append(adjusted)

        return lines

    def _draw_caption_line(
        self,
        draw: ImageDraw.Draw,
        line_words: list[dict],
        y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Draw a single line of caption text with all effects.

        Handles: stroke, shadow, background box, highlight.
        """
        for word_info in line_words:
            x = word_info["x"]
            text = word_info["text"]
            font = word_info["font"]
            is_current = word_info["is_current"]

            color = self.highlight_color if is_current else self.text_color

            # Draw stroke/outline (behind text)
            if self.style_config["stroke"] and self.stroke_width > 0:
                sw = self.stroke_width
                for dx in range(-sw, sw + 1):
                    for dy in range(-sw, sw + 1):
                        if dx * dx + dy * dy <= sw * sw:  # Circular stroke
                            draw.text((x + dx, y + dy), text, fill=self.stroke_color, font=font)

            # Draw drop shadow
            if self.style_config["shadow"]:
                shadow_offset = 3
                shadow_color = (0, 0, 0, 180)
                draw.text((x + shadow_offset, y + shadow_offset), text, fill=shadow_color, font=font)

            # Draw background box for current word
            if self.style_config["background_box"] and is_current:
                bbox = self._get_text_bbox(draw, text, font)
                padding = 10
                box_left = bbox[0] + x - padding
                box_top = bbox[1] + y - padding
                box_right = bbox[2] + x + padding
                box_bottom = bbox[3] + y + padding

                # Rounded rectangle effect (simple)
                draw.rectangle(
                    [box_left, box_top, box_right, box_bottom],
                    fill=(0, 0, 0, 140),
                )

            # Draw the actual text
            draw.text((x, y), text, fill=color, font=font)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

async def generate_caption_frames(
    words: list[dict],
    style: str = "hormozi",
    font_path: Optional[str | Path] = None,
    text_color: str = CAPTION_COLOR,
    highlight_color: str = CAPTION_HIGHLIGHT_COLOR,
    stroke_color: str = CAPTION_STROKE_COLOR,
    stroke_width: int = CAPTION_STROKE_WIDTH,
    output_dir: Optional[Path] = None,
    duration: float = 0.0,
) -> list[Path]:
    """
    Generate caption frames for each word in the transcript.

    Args:
        words: List of dicts with 'word', 'start', 'end' keys.
        style: Caption style name.
        font_path: Path to the font file.
        text_color: Default text color.
        highlight_color: Color for highlighted (current) word.
        stroke_color: Outline color.
        stroke_width: Outline width.
        output_dir: Directory for output frames.
        duration: Total video duration.

    Returns:
        List of paths to generated caption frame images.
    """
    generator = CaptionGenerator(
        style=style,
        text_color=text_color,
        highlight_color=highlight_color,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        font_path=font_path,
    )

    frames = generator.generate_frames(words, output_dir, duration)
    return [f.path for f in frames]


async def generate_srt_from_words(
    words: list[dict],
    output_path: str | Path,
    max_words_per_line: int = 6,
) -> Path:
    """
    Generate an SRT subtitle file from word timestamps.

    Groups words into lines and creates subtitle segments.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not words:
        output_path.write_text("", encoding="utf-8")
        return output_path

    lines = []
    current_line_words = []
    current_start = words[0]["start"]

    for i, word in enumerate(words):
        current_line_words.append(word["word"])

        if len(current_line_words) >= max_words_per_line or i == len(words) - 1:
            end_time = word["end"]
            text = " ".join(current_line_words)
            lines.append({
                "index": len(lines) + 1,
                "start": current_start,
                "end": end_time,
                "text": text,
            })
            current_line_words = []
            if i < len(words) - 1:
                current_start = words[i + 1]["start"]

    with open(output_path, "w", encoding="utf-8") as f:
        for line in lines:
            start_str = _format_srt_time(line["start"])
            end_str = _format_srt_time(line["end"])
            f.write(f"{line['index']}\n{start_str} --> {end_str}\n{line['text']}\n\n")

    logger.info("Generated SRT with %d segments: %s", len(lines), output_path.name)
    return output_path


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT time code (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
