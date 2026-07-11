from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from app.domain.enums import Focus, MascotAnchor, MascotPose
from app.domain.models import CaptionCue, CompiledVideoSpec
from app.rendering.coordinates import Region, TemplateConfig, load_template
from app.rendering.text_layout import load_font, measure_text
from app.services.mascot_calibration_service import MascotCalibrationService, PoseCalibration


class ReferenceRenderer:
    def __init__(
        self,
        templates_dir: Path,
        mascots_dir: Path,
        font_path: Optional[Path] = None,
    ):
        self.template = load_template("reference_v1", templates_dir)
        self.mascots_dir = mascots_dir
        self.font_path = font_path
        self._images: dict[Path, Image.Image] = {}
        self._mascot_paths = self._load_mascot_paths()
        self._calibration_service = MascotCalibrationService(mascots_dir)
        self._calibration = self._calibration_service.load()

    def compose_frame(self, spec: CompiledVideoSpec, time_seconds: float) -> Image.Image:
        canvas = Image.new(
            "RGBA",
            (self.template.canvas_width, self.template.canvas_height),
            (*self.template.background_color, 255),
        )
        draw = ImageDraw.Draw(canvas)
        self._draw_product(
            canvas,
            spec.left_image,
            self.template.region("left_image"),
            self.product_scale_at(spec, time_seconds, Focus.LEFT),
        )
        self._draw_product(
            canvas,
            spec.right_image,
            self.template.region("right_image"),
            self.product_scale_at(spec, time_seconds, Focus.RIGHT),
        )
        self._draw_label(draw, spec.left_label, self.template.region("left_label"))
        self._draw_label(draw, spec.right_label, self.template.region("right_label"))
        self._draw_caption(draw, self._caption_at(spec.captions, time_seconds))
        self._draw_mascot(canvas, spec, time_seconds)
        if self.cta_visible_at(spec, time_seconds):
            self._draw_cta(draw)
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
        current, previous, change_start = self._mascot_state(spec, time_seconds)
        progress = min(max((time_seconds - change_start) / 0.18, 0.0), 1.0)
        eased = 1.0 - (1.0 - progress) ** 3
        previous_pose = self._calibration.poses[previous.mascot_pose.value]
        current_pose = self._calibration.poses[current.mascot_pose.value]
        previous_x = previous_pose.x + self._anchor_offset(previous.mascot_anchor)
        current_x = current_pose.x + self._anchor_offset(current.mascot_anchor)
        x = previous_x + (current_x - previous_x) * eased
        y = previous_pose.y + (current_pose.y - previous_pose.y) * eased
        return round(x, 4), round(y, 4)

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
        default = type("Cue", (), {
            "mascot_pose": MascotPose.NEUTRAL,
            "mascot_anchor": MascotAnchor.CENTER,
            "start": 0.0,
        })()
        previous = default
        current = default
        change_start = 0.0
        for cue in spec.direction_cues:
            if cue.start > time_seconds:
                break
            previous = current
            current = cue
            change_start = cue.start
        return current, previous, change_start

    def _draw_product(
        self,
        canvas: Image.Image,
        path: Path,
        region: Region,
        scale: float,
    ) -> None:
        image = self._image(path)
        fitted = self._fit(image, region, scale)
        x = region.center[0] - fitted.width // 2
        y = region.center[1] - fitted.height // 2
        canvas.alpha_composite(fitted, (x, y))

    def _draw_label(self, draw: ImageDraw.ImageDraw, text: str, region: Region) -> None:
        font = load_font(self.font_path, self.template.fonts["label"].size)
        width, height = measure_text(text, font)
        draw.text(
            (region.center[0] - width // 2, region.center[1] - height // 2),
            text,
            font=font,
            fill=self.template.fonts["label"].color,
            stroke_width=1,
            stroke_fill=(255, 255, 255),
        )

    def _draw_caption(self, draw: ImageDraw.ImageDraw, cue: Optional[CaptionCue]) -> None:
        if cue is None:
            return
        region = self.template.region("caption")
        font = load_font(self.font_path, self.template.fonts["caption"].size)
        palette = [(243, 199, 181), (246, 229, 154), (191, 217, 138), (229, 184, 206)]
        measurements = [measure_text(word, font) for word in cue.words]
        padding_x = 16
        gap = 12
        total_width = sum(width + padding_x * 2 for width, _ in measurements) + gap * (len(cue.words) - 1)
        x = region.center[0] - total_width // 2
        max_height = max(height for _, height in measurements)
        y = region.center[1] - max_height // 2 - 12
        for index, (word, (width, height)) in enumerate(zip(cue.words, measurements)):
            color = palette[index % len(palette)]
            box = (x, y, x + width + padding_x * 2, y + max_height + 24)
            draw.rounded_rectangle(box, radius=10, fill=color)
            draw.text(
                (x + padding_x, y + (max_height - height) // 2),
                word,
                font=font,
                fill=(15, 15, 15),
            )
            x += width + padding_x * 2 + gap

    def _draw_mascot(
        self,
        canvas: Image.Image,
        spec: CompiledVideoSpec,
        time_seconds: float,
    ) -> None:
        current, _, change_start = self._mascot_state(spec, time_seconds)
        pop_progress = min(max((time_seconds - change_start) / 0.1, 0.0), 1.0)
        pop_scale = 1.0 + 0.06 * math.sin(math.pi * pop_progress)
        pivot_x, pivot_y = self.mascot_pivot_at(spec, time_seconds)
        configured = self._calibration.poses[current.mascot_pose.value]
        animated = PoseCalibration(
            x=pivot_x,
            y=pivot_y,
            scale=configured.scale,
        )
        self._calibration_service.paste_calibrated_pose(
            canvas,
            current.mascot_pose.value,
            animated,
            self._calibration,
            extra_scale=pop_scale,
        )

    def _draw_cta(self, draw: ImageDraw.ImageDraw) -> None:
        region = self.template.region("cta")
        draw.rounded_rectangle(
            (region.x, region.y, region.x2, region.y2),
            radius=14,
            fill=(216, 184, 122),
            outline=(30, 30, 30),
            width=4,
        )
        font = load_font(self.font_path, self.template.fonts["cta"].size)
        text = "LIKE • SHARE • FOLLOW"
        width, height = measure_text(text, font)
        draw.text(
            (region.center[0] - width // 2, region.center[1] - height // 2),
            text,
            font=font,
            fill=self.template.fonts["cta"].color,
        )

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
            self._images[path] = Image.open(path).convert("RGBA")
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
