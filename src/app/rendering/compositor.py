from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from app.domain.enums import Focus
from app.domain.models import RenderSpec, SceneSpec
from app.rendering.coordinates import Region, TemplateConfig
from app.rendering.text_layout import draw_centered_text, draw_left_aligned_text


class Compositor:
    def __init__(
        self,
        template: TemplateConfig,
        font_path: Optional[Path] = None,
    ):
        self.template = template
        self.font_path = font_path
        self._image_cache: dict[Path, Image.Image] = {}

    def compose_frame(
        self,
        spec: RenderSpec,
        scene: SceneSpec,
    ) -> Image.Image:
        t = self.template
        canvas = Image.new("RGBA", (t.canvas_width, t.canvas_height), (*t.background_color, 255))
        draw = ImageDraw.Draw(canvas)

        self._draw_title(canvas, draw, spec.title)
        self._draw_labels(canvas, draw, spec.left_label, spec.right_label)
        self._draw_images(canvas, draw, spec.left_image, spec.right_image)
        self._draw_focus_highlight(canvas, scene.focus)
        self._draw_phrase(canvas, draw, scene.phrase)
        self._draw_mascot(canvas, scene.pose)

        return canvas.convert("RGB")

    def _draw_title(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        title: str,
    ) -> None:
        region = self.template.region("title")
        font_cfg = self.template.fonts.get("title")
        color = font_cfg.color if font_cfg else (255, 255, 255)
        max_size = font_cfg.size if font_cfg else 64

        draw_centered_text(
            draw,
            title,
            region,
            self.font_path,
            color=color,
            max_size=max_size,
            min_size=24,
            max_lines=2,
            stroke_color=(0, 0, 0),
            stroke_width=2,
        )

    def _draw_labels(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        left_label: str,
        right_label: str,
    ) -> None:
        font_cfg = self.template.fonts.get("label")
        color = font_cfg.color if font_cfg else (220, 220, 230)
        size = font_cfg.size if font_cfg else 36

        left_region = self.template.region("left_label")
        right_region = self.template.region("right_label")

        draw_centered_text(
            draw,
            left_label,
            left_region,
            self.font_path,
            color=color,
            max_size=size,
            min_size=18,
            max_lines=1,
            stroke_color=(0, 0, 0),
            stroke_width=1,
        )
        draw_centered_text(
            draw,
            right_label,
            right_region,
            self.font_path,
            color=color,
            max_size=size,
            min_size=18,
            max_lines=1,
            stroke_color=(0, 0, 0),
            stroke_width=1,
        )

    def _draw_images(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        left_path: Path,
        right_path: Path,
    ) -> None:
        left_region = self.template.region("left_image")
        right_region = self.template.region("right_image")

        left_img = self._load_image(left_path)
        right_img = self._load_image(right_path)

        left_resized = self._fit_image(left_img, left_region)
        right_resized = self._fit_image(right_img, right_region)

        lx = left_region.center[0] - left_resized.width // 2
        ly = left_region.center[1] - left_resized.height // 2
        rx = right_region.center[0] - right_resized.width // 2
        ry = right_region.center[1] - right_resized.height // 2

        if left_resized.mode == "RGBA":
            canvas.paste(left_resized, (lx, ly), left_resized)
        else:
            canvas.paste(left_resized, (lx, ly))

        if right_resized.mode == "RGBA":
            canvas.paste(right_resized, (rx, ry), right_resized)
        else:
            canvas.paste(right_resized, (rx, ry))

        divider_x = (left_region.x2 + right_region.x) // 2
        draw.line(
            [(divider_x, left_region.y - 10), (divider_x, left_region.y2 + 10)],
            fill=(80, 80, 100, 200),
            width=3,
        )

    def _draw_focus_highlight(
        self,
        canvas: Image.Image,
        focus: Focus,
    ) -> None:
        if focus in (Focus.NEUTRAL, Focus.BOTH):
            if focus == Focus.BOTH:
                self._draw_border_around(canvas, self.template.region("left_image"))
                self._draw_border_around(canvas, self.template.region("right_image"))
            return
        if focus == Focus.LEFT:
            region = self.template.region("left_image")
        elif focus == Focus.RIGHT:
            region = self.template.region("right_image")
        else:
            return
        self._draw_border_around(canvas, region)

    def _draw_border_around(self, canvas: Image.Image, region: Region) -> None:
        fh = self.template.focus_highlight
        margin = fh.border_width + 4
        rect = [
            region.x - margin,
            region.y - margin,
            region.x2 + margin,
            region.y2 + margin,
        ]
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            rect,
            radius=max(8, margin),
            outline=(*fh.color, fh.alpha),
            width=fh.border_width,
        )
        canvas.paste(overlay, (0, 0), overlay)

    def _draw_phrase(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        phrase: str,
    ) -> None:
        if not phrase:
            return
        region = self.template.region("phrase")
        font_cfg = self.template.fonts.get("phrase")
        color = font_cfg.color if font_cfg else (255, 210, 80)
        max_size = font_cfg.size if font_cfg else 72

        draw_centered_text(
            draw,
            phrase,
            region,
            self.font_path,
            color=color,
            max_size=max_size,
            min_size=24,
            max_lines=2,
            stroke_color=(0, 0, 0),
            stroke_width=4,
            bg_box=True,
            bg_color=(10, 10, 20),
            bg_alpha=140,
        )

    def _draw_mascot(
        self,
        canvas: Image.Image,
        pose_name: str,
    ) -> None:
        pose_path = self._resolve_mascot_path(pose_name)
        if pose_path is None or not pose_path.exists():
            return

        mascot_img = self._load_image(pose_path)
        mascot_region = self.template.region("mascot")
        sized = self._fit_image(mascot_img, mascot_region)

        mx = mascot_region.center[0] - sized.width // 2
        my = mascot_region.center[1] - sized.height // 2

        if sized.mode == "RGBA":
            canvas.paste(sized, (mx, my), sized)
        else:
            canvas.paste(sized, (mx, my))

    def _resolve_mascot_path(self, pose_name: str) -> Optional[Path]:
        from app.config import get_settings

        settings = get_settings()
        mascot_dir = settings.mascots_dir
        meta_path = mascot_dir / "mascot_meta.json"

        if meta_path.exists():
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            poses = meta.get("poses", {})
            if pose_name in poses:
                return mascot_dir / poses[pose_name]

        candidate = mascot_dir / f"{pose_name}.png"
        if candidate.exists():
            return candidate
        return None

    def _load_image(self, path: Path) -> Image.Image:
        if path in self._image_cache:
            return self._image_cache[path].copy()
        img = Image.open(path).convert("RGBA")
        self._image_cache[path] = img
        return img.copy()

    @staticmethod
    def _fit_image(image: Image.Image, region: Region) -> Image.Image:
        scale = min(region.width / image.width, region.height / image.height)
        new_w = max(1, int(image.width * scale))
        new_h = max(1, int(image.height * scale))
        return image.resize((new_w, new_h), Image.LANCZOS)

    def create_contact_sheet(
        self,
        frames: list[Path],
        cols: int = 3,
        thumb_width: int = 360,
    ) -> Image.Image:
        if not frames:
            raise ValueError("No frames to create contact sheet from")

        loaded = [Image.open(f).convert("RGB") for f in frames]
        thumb_h = int(thumb_width * loaded[0].height / loaded[0].width)

        rows = (len(loaded) + cols - 1) // cols
        padding = 10
        sheet_w = cols * thumb_width + (cols + 1) * padding
        sheet_h = rows * thumb_h + (rows + 1) * padding

        sheet = Image.new("RGB", (sheet_w, sheet_h), (30, 30, 40))
        draw = ImageDraw.Draw(sheet)

        for i, img in enumerate(loaded):
            thumb = img.resize((thumb_width, thumb_h), Image.LANCZOS)
            col = i % cols
            row = i // cols
            x = padding + col * (thumb_width + padding)
            y = padding + row * (thumb_h + padding)
            sheet.paste(thumb, (x, y))
            draw.rectangle([x, y, x + thumb_width, y + thumb_h], outline=(60, 60, 80), width=1)

        return sheet
