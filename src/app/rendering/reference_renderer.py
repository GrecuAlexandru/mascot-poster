from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from app.domain.enums import Focus, MascotAnchor, MascotPose, VisualEventKind
from app.domain.models import CaptionCue, CompiledVideoSpec, VisualEvent
from app.rendering.coordinates import Region, TemplateConfig, load_template
from app.rendering.text_layout import fit_text, load_font, measure_text, wrap_text
from app.services.mascot_calibration_service import MascotCalibrationService, PoseCalibration
from app.services.product_asset_normalizer import ProductAssetNormalizer


@dataclass(frozen=True)
class CaptionCardStyle:
    fill: tuple[int, int, int]
    rotation_degrees: int
    corner_offsets: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]


class ReferenceRenderer:
    caption_card_colors = ((232, 117, 96), (242, 193, 78), (120, 198, 163))
    caption_text_color = (36, 31, 26)
    caption_active_scale = 1.0
    caption_active_lift = 0
    caption_font_size = 76
    caption_min_font_size = 36
    caption_height_sample = "ĂÂÎȘȚgj"
    caption_word_gap_ratio = 0.10
    caption_line_height_ratio = 1.08
    thumbnail_left_color = (255, 196, 61)
    thumbnail_right_color = (104, 211, 176)
    thumbnail_shadow_color = (232, 117, 96)
    thumbnail_outline_color = (48, 36, 24)
    thumbnail_left_region = Region(x=90, y=80, width=900, height=190)
    thumbnail_vs_region = Region(x=430, y=295, width=220, height=100)
    thumbnail_right_region = Region(x=90, y=420, width=900, height=190)
    thumbnail_mascot_top = 660

    def __init__(
        self,
        templates_dir: Path,
        mascots_dir: Path,
        font_path: Optional[Path] = None,
    ):
        self.template = load_template("reference_v1", templates_dir)
        self.mascots_dir = mascots_dir
        self.font_path = font_path
        self._label_font_path = self._resolve_label_font_path(font_path)
        self._cta_font_path = self._resolve_cta_font_path(font_path)
        self._thumbnail_font_path = templates_dir.parent / "assets" / "fonts" / "Coiny-Regular.ttf"
        self._thumbnail_vs_font_path = self._cta_font_path
        self._images: dict[Path, tuple[tuple[int, int, int], Image.Image]] = {}
        self._bubble_cache: dict[str, tuple[Image.Image, int]] = {}
        self._mascot_paths = self._load_mascot_paths()
        self._calibration_service = MascotCalibrationService(mascots_dir)
        self._calibration = self._calibration_service.load()
        self._product_normalizer = ProductAssetNormalizer(padding_pixels=4)

    @property
    def calibration_path(self) -> Path:
        return self._calibration_service.config_path

    @staticmethod
    def _resolve_label_font_path(font_path: Optional[Path]) -> Optional[Path]:
        candidate = Path("C:/Windows/Fonts/arialbi.ttf")
        return candidate if candidate.exists() else font_path

    @staticmethod
    def _resolve_cta_font_path(font_path: Optional[Path]) -> Optional[Path]:
        candidate = Path("C:/Windows/Fonts/arialbd.ttf")
        return candidate if candidate.exists() else font_path

    def compose_frame(self, spec: CompiledVideoSpec, time_seconds: float) -> Image.Image:
        canvas = Image.new(
            "RGBA",
            (self.template.canvas_width, self.template.canvas_height),
            (*self.template.background_color, 255),
        )
        draw = ImageDraw.Draw(canvas)
        left_progress = self._product_visibility(spec, time_seconds, VisualEventKind.REVEAL_LEFT)
        right_progress = self._product_visibility(spec, time_seconds, VisualEventKind.REVEAL_RIGHT)
        self._draw_product_pair(
            canvas,
            spec.left_image,
            spec.right_image,
            self.template.region("left_image"),
            self.template.region("right_image"),
            self.product_scale_at(spec, time_seconds, Focus.LEFT),
            self.product_scale_at(spec, time_seconds, Focus.RIGHT),
            left_progress,
            right_progress,
        )
        cta_visible = self.cta_visible_at(spec, time_seconds)
        if not cta_visible:
            self._draw_label(
                canvas,
                spec.left_label,
                self.template.region("left_label"),
                left_progress,
            )
            self._draw_label(
                canvas,
                spec.right_label,
                self.template.region("right_label"),
                right_progress,
            )
            self._draw_caption(canvas, self._caption_at(spec.captions, time_seconds))
        self._draw_mascot(canvas, spec, time_seconds)
        if cta_visible:
            self._draw_cta(canvas, spec, time_seconds)
        return canvas.convert("RGB")

    def compose_thumbnail(self, spec: CompiledVideoSpec) -> Image.Image:
        canvas = Image.new(
            "RGBA",
            (self.template.canvas_width, self.template.canvas_height),
            (*self.template.background_color, 255),
        )
        draw = ImageDraw.Draw(canvas)
        self._draw_thumbnail_label(
            draw,
            spec.left_label.upper(),
            self.thumbnail_left_region,
            self.thumbnail_left_color,
        )
        self._draw_thumbnail_vs(draw)
        self._draw_thumbnail_label(
            draw,
            spec.right_label.upper(),
            self.thumbnail_right_region,
            self.thumbnail_right_color,
        )
        pose = "intro_hands_up" if "intro_hands_up" in self._mascot_paths else "neutral"
        configured = self._calibration.poses[pose]
        self._calibration_service.paste_calibrated_pose(
            canvas,
            pose,
            PoseCalibration(
                x=self.template.canvas_width / 2,
                y=1600,
                scale=configured.scale * 1.25,
            ),
            self._calibration,
        )
        return canvas.convert("RGB")

    def _thumbnail_label_layout(self, text: str, region: Region):
        for size in range(126, 11, -2):
            font = load_font(self._thumbnail_font_path, size)
            lines = wrap_text(text, font, region.width - 28, 2)
            line_height = measure_text("Ag", font)[1] + 10
            if (
                len(lines) <= 2
                and line_height * len(lines) <= region.height - 20
                and all(measure_text(line, font)[0] <= region.width - 28 for line in lines)
            ):
                return font, lines
        font = load_font(self._thumbnail_font_path, 10)
        return font, wrap_text(text, font, region.width - 28, 2)

    def _draw_thumbnail_label(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        region: Region,
        fill: tuple[int, int, int],
    ) -> None:
        font, lines = self._thumbnail_label_layout(text, region)
        line_height = measure_text("Ag", font)[1] + 10
        total_height = line_height * len(lines)
        y = region.center[1] - total_height // 2
        stroke_width = max(5, font.size // 16)
        shadow_offset = max(7, font.size // 12)
        for line in lines:
            width = measure_text(line, font)[0]
            x = region.center[0] - width // 2
            draw.text(
                (x + shadow_offset, y + shadow_offset),
                line,
                font=font,
                fill=self.thumbnail_shadow_color,
                stroke_width=stroke_width,
                stroke_fill=self.thumbnail_outline_color,
            )
            draw.text(
                (x, y),
                line,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=self.thumbnail_outline_color,
            )
            y += line_height

    def _draw_thumbnail_vs(self, draw: ImageDraw.ImageDraw) -> None:
        region = self.thumbnail_vs_region
        shadow = 8
        draw.rounded_rectangle(
            (region.x + shadow, region.y + shadow, region.x2 + shadow, region.y2 + shadow),
            radius=42,
            fill=self.thumbnail_outline_color,
        )
        draw.rounded_rectangle(
            (region.x, region.y, region.x2, region.y2),
            radius=42,
            fill=self.thumbnail_shadow_color,
            outline=self.thumbnail_outline_color,
            width=6,
        )
        font = load_font(self._thumbnail_vs_font_path, 68)
        width, height = measure_text("VS", font)
        draw.text(
            (region.center[0] - width // 2, region.center[1] - height // 2 - 6),
            "VS",
            font=font,
            fill=(255, 255, 255),
        )

    def iter_frames(self, spec: CompiledVideoSpec):
        frame_count = max(1, math.ceil(spec.total_duration_seconds * spec.fps))
        for frame_index in range(frame_count):
            yield self.compose_frame(spec, frame_index / spec.fps)

    @staticmethod
    def cta_visible_at(spec: CompiledVideoSpec, time_seconds: float) -> bool:
        return spec.cta_start_seconds <= time_seconds < spec.total_duration_seconds

    def product_scale_at(
        self,
        spec: CompiledVideoSpec,
        time_seconds: float,
        side: Focus,
    ) -> float:
        current_focus, previous_focus, change_start = self._focus_state(spec, time_seconds)
        progress = min(max((time_seconds - change_start) / 0.18, 0.0), 1.0)
        eased = 1.0 - (1.0 - progress) ** 3
        previous_scale = 1.12 if previous_focus == side else 1.0
        target_scale = 1.12 if current_focus == side else 1.0
        return round(previous_scale + (target_scale - previous_scale) * eased, 4)

    @staticmethod
    def visual_event_progress(event: VisualEvent, time_seconds: float) -> float:
        progress = min(max((time_seconds - event.start) / event.duration_seconds, 0.0), 1.0)
        return 1.0 - (1.0 - progress) ** 3

    @staticmethod
    def entrance_scale(progress: float) -> float:
        return 0.86 + 0.14 * progress

    def _product_visibility(
        self,
        spec: CompiledVideoSpec,
        time_seconds: float,
        kind: VisualEventKind,
    ) -> float:
        if not spec.visual_events:
            return 1.0
        event = next((event for event in spec.visual_events if event.kind == kind), None)
        if event is None:
            return 0.0
        return self.visual_event_progress(event, time_seconds)

    def mascot_x_at(self, spec: CompiledVideoSpec, time_seconds: float) -> float:
        return self.mascot_pivot_at(spec, time_seconds)[0]

    def mascot_pivot_at(
        self,
        spec: CompiledVideoSpec,
        time_seconds: float,
    ) -> tuple[float, float]:
        current = self._mascot_state(spec, time_seconds)
        pose = self._calibration.poses[current.mascot_pose.value]
        x = pose.x + self._anchor_offset(current.mascot_anchor)
        return round(x, 4), round(pose.y, 4)

    def _focus_state(self, spec: CompiledVideoSpec, time_seconds: float):
        previous = Focus.NEUTRAL
        current = Focus.NEUTRAL
        change_start = 0.0
        for cue in spec.direction_cues:
            if cue.start > time_seconds:
                break
            if cue.product_focus != current:
                previous = current
                current = cue.product_focus
                change_start = cue.start
        return current, previous, change_start

    def _mascot_state(self, spec: CompiledVideoSpec, time_seconds: float):
        current = type("Cue", (), {
            "mascot_pose": MascotPose.NEUTRAL,
            "mascot_anchor": MascotAnchor.CENTER,
            "start": 0.0,
        })()
        for cue in spec.direction_cues:
            if cue.start > time_seconds:
                break
            current = cue
        return current

    def _draw_product_pair(
        self,
        canvas: Image.Image,
        left_path: Path,
        right_path: Path,
        left_region: Region,
        right_region: Region,
        left_scale: float,
        right_scale: float,
        left_progress: float,
        right_progress: float,
    ) -> None:
        left_image = self._image(left_path)
        right_image = self._image(right_path)
        left_fitted, right_fitted = self._fit_pair(
            left_image,
            right_image,
            left_region,
            right_region,
            left_scale * self.entrance_scale(left_progress),
            right_scale * self.entrance_scale(right_progress),
        )
        if left_progress > 0.0:
            self._paste_centered(canvas, self._with_opacity(left_fitted, left_progress), left_region)
        if right_progress > 0.0:
            self._paste_centered(canvas, self._with_opacity(right_fitted, right_progress), right_region)

    @staticmethod
    def _with_opacity(image: Image.Image, opacity: float) -> Image.Image:
        if opacity >= 1.0:
            return image
        faded = image.copy()
        faded.putalpha(faded.getchannel("A").point(lambda value: round(value * opacity)))
        return faded

    @staticmethod
    def _paste_centered(canvas: Image.Image, fitted: Image.Image, region: Region) -> None:
        x = region.center[0] - fitted.width // 2
        y = region.center[1] - fitted.height // 2
        canvas.alpha_composite(fitted, (x, y))

    @staticmethod
    def _fit_pair(
        left_image: Image.Image,
        right_image: Image.Image,
        left_region: Region,
        right_region: Region,
        left_scale: float,
        right_scale: float,
    ) -> tuple[Image.Image, Image.Image]:
        left_visible = left_image.getchannel("A").point(
            lambda value: 255 if value >= 128 else 0,
        )
        right_visible = right_image.getchannel("A").point(
            lambda value: 255 if value >= 128 else 0,
        )
        left_bbox = left_visible.getbbox() or (0, 0, *left_image.size)
        right_bbox = right_visible.getbbox() or (0, 0, *right_image.size)
        left_visible_width = left_bbox[2] - left_bbox[0]
        left_visible_height = left_bbox[3] - left_bbox[1]
        right_visible_width = right_bbox[2] - right_bbox[0]
        right_visible_height = right_bbox[3] - right_bbox[1]
        target_height = min(
            left_region.height * 0.88,
            right_region.height * 0.88,
            left_region.width * 0.92 * left_visible_height / left_visible_width,
            right_region.width * 0.92 * right_visible_height / right_visible_width,
        )

        def resize(image: Image.Image, visible_height: int, scale: float) -> Image.Image:
            factor = target_height / visible_height * scale
            return image.resize(
                (
                    max(1, round(image.width * factor)),
                    max(1, round(image.height * factor)),
                ),
                Image.Resampling.LANCZOS,
            )

        return (
            resize(left_image, left_visible_height, left_scale),
            resize(right_image, right_visible_height, right_scale),
        )

    def _draw_label(
        self,
        canvas: Image.Image,
        text: str,
        region: Region,
        opacity: float = 1.0,
    ) -> None:
        if opacity <= 0.0:
            return
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font, lines, _ = fit_text(
            text,
            region,
            self._label_font_path,
            max_size=72,
            min_size=30,
            max_lines=2,
        )
        line_height = measure_text("Ag", font)[1] + 8
        total_height = line_height * len(lines)
        stroke = max(6, font.size // 8)
        shadow_offset = max(3, font.size // 18)
        for index, line in enumerate(lines):
            width = measure_text(line, font)[0]
            position = (
                region.center[0] - width // 2,
                region.center[1] - total_height // 2 + index * line_height,
            )
            draw.text(
                (
                    position[0] + shadow_offset,
                    position[1] + shadow_offset,
                ),
                line,
                font=font,
                fill=(18, 18, 22),
                stroke_width=stroke,
                stroke_fill=(18, 18, 22),
            )
            draw.text(
                position,
                line,
                font=font,
                fill=(255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(18, 18, 22),
            )
        canvas.alpha_composite(self._with_opacity(layer, opacity))

    def _draw_caption(self, canvas: Image.Image, cue: Optional[CaptionCue]) -> None:
        if cue is None:
            return
        region = self.template.region("caption")
        slot_words = cue.slot_words or cue.words
        font, lines = self._caption_layout(slot_words, region)
        gap = max(8, round(font.size * self.caption_word_gap_ratio))
        line_gap = max(4, round(font.size * 0.05))
        rendered_lines: list[list[tuple[Image.Image, bool]]] = []
        word_index = 0
        for line in lines:
            rendered_line: list[tuple[Image.Image, bool]] = []
            for word in line:
                visible = word_index < len(cue.words)
                style = self.caption_card_style(word, word_index)
                rendered_line.append((self._build_caption_card(word, font, style, False), visible))
                word_index += 1
            rendered_lines.append(rendered_line)
        line_heights = [
            max(card.height for card, _ in line) + self.caption_active_lift
            for line in rendered_lines
        ]
        total_height = sum(line_heights) + line_gap * (len(rendered_lines) - 1)
        y = max(region.y, min(region.center[1] - total_height // 2, region.y2 - total_height))
        for line, line_height in zip(rendered_lines, line_heights):
            line_width = sum(card.width for card, _ in line) + gap * (len(line) - 1)
            x = max(region.x, min(region.center[0] - line_width // 2, region.x2 - line_width))
            for card, visible in line:
                paste_y = y + (line_height - card.height) // 2
                if visible:
                    canvas.alpha_composite(card, (x, paste_y))
                x += card.width + gap
            y += line_height + line_gap

    def caption_card_style(self, word: str, index: int) -> CaptionCardStyle:
        return CaptionCardStyle(
            fill=self.caption_card_colors[index % len(self.caption_card_colors)],
            rotation_degrees=0,
            corner_offsets=((0, 0), (0, 0), (0, 0), (0, 0)),
        )

    def _build_caption_card(
        self,
        word: str,
        font,
        style: CaptionCardStyle,
        active: bool,
    ) -> Image.Image:
        measurement = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        bbox = ImageDraw.Draw(measurement).textbbox((0, 0), word, font=font)
        height_bbox = ImageDraw.Draw(measurement).textbbox(
            (0, 0),
            self.caption_height_sample,
            font=font,
        )
        text_width = bbox[2] - bbox[0]
        text_height = height_bbox[3] - height_bbox[1]
        padding_x = max(14, round(font.size * 0.14))
        padding_y = max(8, round(font.size * 0.08))
        card_width = text_width + padding_x * 2
        card_height = text_height + padding_y * 2
        shadow_offset = max(4, round(font.size * 0.04))
        content = Image.new(
            "RGBA",
            (card_width, card_height + shadow_offset),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(content)
        radius = max(8, round(font.size * 0.09))
        shadow_alpha = 58
        draw.rounded_rectangle(
            (0, shadow_offset, card_width - 1, card_height + shadow_offset - 1),
            radius=radius,
            fill=(*self.caption_text_color, shadow_alpha),
        )
        draw.rounded_rectangle(
            (0, 0, card_width - 1, card_height - 1),
            radius=radius,
            fill=(*style.fill, 255),
            outline=None,
            width=1,
        )
        draw.text(
            (
                (card_width - text_width) // 2 - bbox[0],
                padding_y - height_bbox[1],
            ),
            word,
            font=font,
            fill=(*self.caption_text_color, 255),
        )
        margin = 8
        layer_width = round(card_width * self.caption_active_scale) + margin * 2
        layer_height = round(
            (card_height + shadow_offset) * self.caption_active_scale,
        ) + margin * 2
        layer = Image.new("RGBA", (layer_width, layer_height), (0, 0, 0, 0))
        layer.alpha_composite(
            content,
            ((layer_width - content.width) // 2, (layer_height - content.height) // 2),
        )
        return layer

    def _caption_layout(self, words: list[str], region: Region):
        size = self.caption_font_size
        while True:
            font = load_font(self.font_path, size)
            gap = max(8, round(size * self.caption_word_gap_ratio))
            lines = self._caption_lines(words, font, region.width - 12)
            fits_width = all(
                sum(self._caption_card_extent(word, font)[0] for word in line)
                + gap * (len(line) - 1)
                <= region.width
                for line in lines
            )
            fits_height = (
                sum(max(self._caption_card_extent(word, font)[1] for word in line) for line in lines)
                + max(0, len(lines) - 1) * max(4, round(size * 0.05))
                + self.caption_active_lift
                <= region.height
            )
            if (fits_width and fits_height) or size <= self.caption_min_font_size:
                return font, lines
            size -= 4

    @staticmethod
    def _caption_card_extent(word: str, font) -> tuple[int, int]:
        width = measure_text(word, font)[0]
        height = measure_text(ReferenceRenderer.caption_height_sample, font)[1]
        scale = ReferenceRenderer.caption_active_scale
        shadow_offset = max(4, round(font.size * 0.04))
        margin = 8
        return (
            round((width + max(28, round(font.size * 0.28))) * scale) + margin * 2,
            round(
                (
                    height
                    + max(16, round(font.size * 0.16))
                    + shadow_offset
                )
                * scale,
            )
            + margin * 2,
        )

    @staticmethod
    def _caption_lines(words: list[str], font, compact_width: int) -> list[list[str]]:
        if len(words) <= 1:
            return [words]
        gap = max(8, round(font.size * ReferenceRenderer.caption_word_gap_ratio))
        widths = [ReferenceRenderer._caption_card_extent(word, font)[0] for word in words]
        if len(words) == 2 and sum(widths) + gap <= compact_width:
            return [words]
        if len(words) == 2:
            return [[words[0]], [words[1]]]
        return [words[:2], words[2:4]]

    def _draw_mascot(
        self,
        canvas: Image.Image,
        spec: CompiledVideoSpec,
        time_seconds: float,
    ) -> None:
        current = self._mascot_state(spec, time_seconds)
        pivot_x, pivot_y = self.mascot_pivot_at(spec, time_seconds)
        configured = self._calibration.poses[current.mascot_pose.value]
        placed = PoseCalibration(
            x=pivot_x,
            y=pivot_y,
            scale=configured.scale,
        )
        self._calibration_service.paste_calibrated_pose(
            canvas,
            current.mascot_pose.value,
            placed,
            self._calibration,
        )

    def _draw_cta(
        self,
        canvas: Image.Image,
        spec: CompiledVideoSpec,
        time_seconds: float,
    ) -> None:
        bubble, anchor_y = self._bubble_cache.get(spec.cta_text, (None, 0))
        if bubble is None:
            bubble, anchor_y = self._build_speech_bubble(spec.cta_text)
            self._bubble_cache[spec.cta_text] = (bubble, anchor_y)

        margin = 24
        paste_x = self.template.canvas_width // 2 - bubble.width // 2
        paste_y = self.template.canvas_height // 2 - bubble.height // 2
        paste_x = max(margin, min(paste_x, self.template.canvas_width - bubble.width - margin))
        paste_y = max(margin, min(paste_y, self.template.canvas_height - bubble.height - margin))
        canvas.alpha_composite(bubble, (paste_x, paste_y))

    def _build_speech_bubble(self, text: str) -> tuple[Image.Image, int]:
        display_text = self._cta_display_text(text)
        font, lines = self._bubble_lines(display_text)
        line_height = measure_text("Ag", font)[1] + 12
        text_h = line_height * len(lines)
        text_w = max((measure_text(line, font)[0] for line in lines), default=1)
        pad_x, pad_y = 46, 34
        body_w = text_w + pad_x * 2
        body_h = text_h + pad_y * 2
        margin = 26
        shadow_offset = 9
        shadow_blur = 14
        shadow_clearance = shadow_offset + shadow_blur * 4
        width = body_w + margin * 2
        body_bottom = margin + body_h
        height = body_bottom + shadow_clearance
        border = (255, 196, 61, 255)

        bubble = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle(
            (
                margin,
                margin + shadow_offset,
                margin + body_w,
                body_bottom + shadow_offset,
            ),
            radius=36,
            fill=(8, 8, 12, 180),
        )
        bubble.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(shadow_blur)))

        draw = ImageDraw.Draw(bubble)
        draw.rounded_rectangle(
            (margin, margin, margin + body_w, body_bottom),
            radius=36,
            fill=(24, 25, 30, 255),
            outline=border,
            width=7,
        )

        y = margin + pad_y
        for line in lines:
            width_line = measure_text(line, font)[0]
            draw.text(
                (width // 2 - width_line // 2, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
            )
            y += line_height

        return bubble, bubble.height

    @staticmethod
    def _cta_display_text(text: str) -> str:
        words = [part.strip().upper() for part in text.split(",") if part.strip()]
        return " · ".join(words)

    def _bubble_lines(self, text: str):
        if "\n" not in text and text == self._cta_display_text("Like, share, follow"):
            return self._single_line_cta_font(text), [text]
        # Honor explicit line breaks, then size the font so the widest paragraph fits.
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        for size in range(60, 33, -4):
            font = load_font(self._cta_font_path, size)
            lines: list[str] = []
            fits = True
            for paragraph in paragraphs:
                wrapped = self._wrap_words(paragraph, font, 760)
                if any(measure_text(line, font)[0] > 760 for line in wrapped):
                    fits = False
                    break
                lines.extend(wrapped)
            if fits and len(lines) <= 4:
                return font, lines
        font = load_font(self._cta_font_path, 34)
        lines = []
        for paragraph in paragraphs:
            lines.extend(self._wrap_words(paragraph, font, 760))
        return font, lines

    def _single_line_cta_font(self, text: str, max_width: int = 760):
        for size in range(60, 11, -2):
            font = load_font(self._cta_font_path, size)
            if measure_text(text, font)[0] <= max_width:
                return font
        return load_font(self._cta_font_path, 12)

    @staticmethod
    def _wrap_words(text: str, font, max_width: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if measure_text(candidate, font)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    @staticmethod
    def _caption_at(captions: list[CaptionCue], time_seconds: float) -> Optional[CaptionCue]:
        for cue in captions:
            if cue.start <= time_seconds < cue.end:
                return cue
        return None

    @staticmethod
    def _anchor_offset(anchor: MascotAnchor) -> float:
        return {
            MascotAnchor.LEFT: -240.0,
            MascotAnchor.CENTER: 0.0,
            MascotAnchor.RIGHT: 240.0,
        }[anchor]

    def _load_mascot_paths(self) -> dict[str, Path]:
        import json

        meta_path = self.mascots_dir / "mascot_meta.json"
        if not meta_path.exists():
            return {}
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            pose: self.mascots_dir / filename
            for pose, filename in meta.get("poses", {}).items()
        }

    def _image(self, path: Path) -> Image.Image:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        cached = self._images.get(path)
        if cached is None or cached[0] != signature:
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            image, _ = self._product_normalizer.crop_visible_subject(image)
            # Crop away transparent padding so the visible object, not the raw
            # image, fills the region — keeps left and right objects the same size.
            self._images[path] = (signature, image)
        return self._images[path][1]

    @staticmethod
    def _fit(image: Image.Image, region: Region, scale: float = 1.0) -> Image.Image:
        max_width = region.width * scale
        max_height = region.height * scale
        factor = min(max_width / image.width, max_height / image.height)
        return image.resize(
            (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
            Image.Resampling.LANCZOS,
        )
