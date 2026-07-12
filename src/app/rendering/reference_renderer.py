from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from app.domain.enums import Focus, MascotAnchor, MascotPose
from app.domain.models import CaptionCue, CompiledVideoSpec
from app.rendering.coordinates import Region, TemplateConfig, load_template
from app.rendering.text_layout import fit_text, load_font, measure_text
from app.services.mascot_calibration_service import MascotCalibrationService, PoseCalibration


class ReferenceRenderer:
    caption_word_gap_ratio = 0.40
    caption_line_height_ratio = 1.38
    caption_highlight_color = (232, 117, 96)

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
        self._images: dict[Path, Image.Image] = {}
        self._bubble_cache: dict[str, tuple[Image.Image, int]] = {}
        self._mascot_paths = self._load_mascot_paths()
        self._calibration_service = MascotCalibrationService(mascots_dir)
        self._calibration = self._calibration_service.load()

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
        self._draw_product_pair(
            canvas,
            spec.left_image,
            spec.right_image,
            self.template.region("left_image"),
            self.template.region("right_image"),
            self.product_scale_at(spec, time_seconds, Focus.LEFT),
            self.product_scale_at(spec, time_seconds, Focus.RIGHT),
        )
        cta_visible = self.cta_visible_at(spec, time_seconds)
        if not cta_visible:
            self._draw_label(canvas, spec.left_label, self.template.region("left_label"))
            self._draw_label(canvas, spec.right_label, self.template.region("right_label"))
            self._draw_caption(draw, self._caption_at(spec.captions, time_seconds))
        self._draw_mascot(canvas, spec, time_seconds)
        if cta_visible:
            self._draw_cta(canvas, spec, time_seconds)
        return canvas.convert("RGB")

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
        previous_scale = 1.28 if previous_focus == side else 1.0
        target_scale = 1.28 if current_focus == side else 1.0
        return round(previous_scale + (target_scale - previous_scale) * eased, 4)

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
    ) -> None:
        left_image = self._image(left_path)
        right_image = self._image(right_path)
        left_fitted, right_fitted = self._fit_pair(
            left_image,
            right_image,
            left_region,
            right_region,
            left_scale,
            right_scale,
        )
        self._paste_centered(canvas, left_fitted, left_region)
        self._paste_centered(canvas, right_fitted, right_region)

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
        def maximum_extent(image: Image.Image, region: Region) -> float:
            factor = min(region.width / image.width, region.height / image.height)
            return max(image.width, image.height) * factor

        target_extent = min(
            maximum_extent(left_image, left_region),
            maximum_extent(right_image, right_region),
        )

        def resize(image: Image.Image, scale: float) -> Image.Image:
            factor = target_extent / max(image.width, image.height) * scale
            return image.resize(
                (
                    max(1, round(image.width * factor)),
                    max(1, round(image.height * factor)),
                ),
                Image.Resampling.LANCZOS,
            )

        return resize(left_image, left_scale), resize(right_image, right_scale)

    def _draw_label(self, canvas: Image.Image, text: str, region: Region) -> None:
        draw = ImageDraw.Draw(canvas)
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

    def _draw_caption(self, draw: ImageDraw.ImageDraw, cue: Optional[CaptionCue]) -> None:
        if cue is None:
            return
        region = self.template.region("caption")
        font, lines = self._caption_layout(cue.words, region)
        stroke = max(3, font.size // 14)
        shadow_offset = max(2, font.size // 20)
        line_height = round(font.size * self.caption_line_height_ratio)
        total_height = line_height * len(lines)
        gap = round(font.size * self.caption_word_gap_ratio)
        word_index = 0
        y = region.center[1] - total_height // 2
        for line in lines:
            widths = [measure_text(word, font)[0] for word in line]
            line_width = sum(widths) + gap * (len(line) - 1)
            x = region.center[0] - line_width // 2
            padding_x = max(12, font.size // 7)
            padding_y = max(10, font.size // 9)
            for word, width in zip(line, widths):
                active = word_index == cue.active_word_index
                if active:
                    text_bbox = draw.textbbox(
                        (x, y),
                        word,
                        font=font,
                        stroke_width=stroke,
                    )
                    draw.rounded_rectangle(
                        (
                            text_bbox[0] - padding_x,
                            text_bbox[1] - padding_y,
                            text_bbox[2] + padding_x,
                            text_bbox[3] + padding_y,
                        ),
                        radius=max(14, font.size // 6),
                        fill=self.caption_highlight_color,
                    )
                fill = (255, 204, 44) if active else (255, 255, 255)
                draw.text(
                    (x + shadow_offset, y + shadow_offset),
                    word,
                    font=font,
                    fill=(20, 20, 20),
                    stroke_width=stroke,
                    stroke_fill=(20, 20, 20),
                )
                draw.text(
                    (x, y),
                    word,
                    font=font,
                    fill=fill,
                    stroke_width=stroke,
                    stroke_fill=(24, 24, 24),
                )
                x += width + gap
                word_index += 1
            y += line_height

    def _caption_layout(self, words: list[str], region: Region):
        size = self.template.fonts["caption"].size
        while True:
            font = load_font(self.font_path, size)
            gap = round(size * self.caption_word_gap_ratio)
            lines = self._caption_lines(words, font, min(region.width, 720))
            fits_width = all(
                sum(measure_text(word, font)[0] for word in line) + gap * (len(line) - 1)
                <= region.width
                for line in lines
            )
            fits_height = round(size * self.caption_line_height_ratio) * len(lines) <= region.height
            if (fits_width and fits_height) or size <= 56:
                return font, lines
            size -= 7

    @staticmethod
    def _caption_lines(words: list[str], font, compact_width: int) -> list[list[str]]:
        if len(words) <= 1:
            return [words]
        if len(words) == 2:
            gap = round(font.size * ReferenceRenderer.caption_word_gap_ratio)
            width = sum(measure_text(word, font)[0] for word in words) + gap
            return [words] if width <= compact_width else [[words[0]], [words[1]]]
        return [words[:2], words[2:]]

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

        mascot_x, _ = self.mascot_pivot_at(spec, time_seconds)
        head_top = self._mascot_head_top(spec, time_seconds)
        card_anchor = (int(mascot_x), int(head_top + 12))

        paste_x = card_anchor[0] - bubble.width // 2
        paste_y = card_anchor[1] - anchor_y
        margin = 24
        paste_x = max(margin, min(paste_x, self.template.canvas_width - bubble.width - margin))
        paste_y = max(margin, paste_y)
        canvas.alpha_composite(bubble, (paste_x, paste_y))

    def _mascot_head_top(self, spec: CompiledVideoSpec, time_seconds: float) -> float:
        current = self._mascot_state(spec, time_seconds)
        configured = self._calibration.poses[current.mascot_pose.value]
        source = self._calibration_service._pose_image(current.mascot_pose.value)
        height = self._calibration.base_render_height * configured.scale
        pivot_y = self._calibration.source_pivot.y * height / source.height
        return configured.y - pivot_y

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
        width = body_w + margin * 2
        height = body_h + margin * 2
        border = (255, 196, 61, 255)
        body_bottom = margin + body_h

        bubble = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle(
            (margin, margin + 9, margin + body_w, body_bottom + 9),
            radius=36,
            fill=(8, 8, 12, 180),
        )
        bubble.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))

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
        if path not in self._images:
            image = Image.open(path).convert("RGBA")
            # Crop away transparent padding so the visible object, not the raw
            # image, fills the region — keeps left and right objects the same size.
            bbox = image.getchannel("A").getbbox()
            if bbox:
                image = image.crop(bbox)
            self._images[path] = image
        return self._images[path]

    @staticmethod
    def _fit(image: Image.Image, region: Region, scale: float = 1.0) -> Image.Image:
        max_width = region.width * scale
        max_height = region.height * scale
        factor = min(max_width / image.width, max_height / image.height)
        return image.resize(
            (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
            Image.Resampling.LANCZOS,
        )
