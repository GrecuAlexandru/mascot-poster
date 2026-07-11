from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.rendering.coordinates import Region


def load_font(font_path: Optional[Path], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path and str(font_path) and Path(font_path).exists():
        return ImageFont.truetype(str(font_path), size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def measure_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    bbox = font.getbbox(text)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def fit_text(
    text: str,
    region: Region,
    font_path: Optional[Path],
    max_size: int = 96,
    min_size: int = 20,
    max_lines: int = 2,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str], int]:
    for size in range(max_size, min_size - 1, -2):
        font = load_font(font_path, size)
        lines = wrap_text(text, font, region.width, max_lines)
        total_height = sum(measure_text(line, font)[1] for line in lines) + 4 * (len(lines) - 1)
        max_line_width = max(measure_text(line, font)[0] for line in lines) if lines else 0
        if total_height <= region.height and max_line_width <= region.width:
            return font, lines, size
    font = load_font(font_path, min_size)
    lines = wrap_text(text, font, region.width, max_lines)
    return font, lines, min_size


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        w = measure_text(candidate, font)[0]
        if w <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) >= max_lines:
            remaining = " ".join(words[len(lines) + 1 :])
            if remaining:
                while measure_text(current + " " + remaining, font)[0] > max_width and len(current) > 3:
                    trim_idx = current.rfind(" ")
                    if trim_idx == -1:
                        break
                    remaining = current[trim_idx + 1 :] + " " + remaining
                    current = current[:trim_idx]
                    if measure_text(current, font)[0] <= max_width:
                        break
                    remaining = current[current.rfind(" ") + 1 :] + " " + remaining
                    current = current[: current.rfind(" ")]
                current = current + " " + remaining
            break
    lines.append(current)

    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1 :])]

    if max_lines == 1 and measure_text(lines[0], font)[0] > max_width:
        while measure_text(lines[0] + "\u2026", font)[0] > max_width and len(lines[0]) > 3:
            lines[0] = lines[0][:-1]
        if measure_text(lines[0] + "\u2026", font)[0] > max_width:
            lines[0] = lines[0][:-1]
        lines[0] = lines[0] + "\u2026"

    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    region: Region,
    font_path: Optional[Path],
    color: tuple[int, int, int] = (255, 255, 255),
    max_size: int = 96,
    min_size: int = 20,
    max_lines: int = 2,
    stroke_color: Optional[tuple[int, int, int]] = None,
    stroke_width: int = 0,
    bg_box: bool = False,
    bg_color: tuple[int, int, int] = (0, 0, 0),
    bg_alpha: int = 160,
) -> None:
    font, lines, _ = fit_text(text, region, font_path, max_size, min_size, max_lines)

    line_height = measure_text("Ag", font)[1] + 4
    total_height = line_height * len(lines)

    if bg_box:
        box_padding = 12
        max_line_width = max(measure_text(line, font)[0] for line in lines) if lines else 0
        box_x1 = region.center[0] - max_line_width // 2 - box_padding
        box_y1 = region.center[1] - total_height // 2 - box_padding
        box_x2 = region.center[0] + max_line_width // 2 + box_padding
        box_y2 = region.center[1] + total_height // 2 + box_padding
        overlay = Image.new("RGBA", draw._image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [box_x1, box_y1, box_x2, box_y2],
            radius=12,
            fill=(*bg_color, bg_alpha),
        )
        draw._image.paste(overlay, (0, 0), overlay)

    for i, line in enumerate(lines):
        line_width = measure_text(line, font)[0]
        x = region.center[0] - line_width // 2
        y = region.center[1] - total_height // 2 + i * line_height

        draw.text(
            (x, y),
            line,
            font=font,
            fill=color,
            stroke_width=stroke_width if stroke_color else 0,
            stroke_fill=stroke_color or (0, 0, 0),
        )


def draw_left_aligned_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    region: Region,
    font_path: Optional[Path],
    color: tuple[int, int, int] = (255, 255, 255),
    size: int = 36,
    stroke_color: Optional[tuple[int, int, int]] = None,
    stroke_width: int = 0,
) -> None:
    font = load_font(font_path, size)
    w = measure_text(text, font)[0]
    font, lines, _ = fit_text(text, region, font_path, size, 16, 2)

    line_height = measure_text("Ag", font)[1] + 4
    for i, line in enumerate(lines):
        y = region.y + i * line_height
        draw.text(
            (region.x, y),
            line,
            font=font,
            fill=color,
            stroke_width=stroke_width if stroke_color else 0,
            stroke_fill=stroke_color or (0, 0, 0),
        )
