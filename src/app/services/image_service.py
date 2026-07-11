from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from app.providers.images.base import GeneratedImage, ImageProvider

logger = logging.getLogger(__name__)

COMPARISON_CANVAS_W = 1080
COMPARISON_CANVAS_H = 700
COMPARISON_HALF_W = COMPARISON_CANVAS_W // 2

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MIN_DIMENSION = 200
_MAX_FILE_SIZE = 20 * 1024 * 1024


class ImageService:
    def __init__(
        self,
        provider: Optional[ImageProvider] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.provider = provider
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def build_prompt(self, item: str, style: str = "product") -> str:
        return (
            f"Professional product photograph of {item}. "
            f"Centered subject, clean white background, no text, no watermark. "
            f"High contrast, consistent lighting, easy to crop. "
            f"Style: {style}."
        )

    async def generate_or_acquire(
        self,
        item: str,
        output_path: Path,
        url: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedImage:
        if url:
            return await self._download_image(url, output_path)

        if not self.provider:
            raise ValueError("No image provider configured and no URL provided")

        prompt = self.build_prompt(item)
        return await self.provider.generate(prompt, output_path, width, height)

    async def _download_image(self, url: str, output_path: Path) -> GeneratedImage:
        from app.providers.images.openai_provider import RemoteImageProvider

        downloader = RemoteImageProvider(cache_dir=self.cache_dir)
        result = await downloader.download(url, output_path)
        self.validate_image(result.path)
        return result

    def validate_image(self, path: Path) -> None:
        if not path.exists():
            raise ValueError(f"Image file not found: {path}")

        file_size = path.stat().st_size
        if file_size > _MAX_FILE_SIZE:
            raise ValueError(f"Image too large: {file_size} bytes (max {_MAX_FILE_SIZE})")
        if file_size == 0:
            raise ValueError(f"Image file is empty: {path}")

        try:
            img = Image.open(path)
            img.verify()
        except Exception as e:
            raise ValueError(f"Image corruption detected: {e}")

        img = Image.open(path)
        if img.width < _MIN_DIMENSION or img.height < _MIN_DIMENSION:
            raise ValueError(
                f"Image dimensions too small: {img.width}x{img.height} "
                f"(min {_MIN_DIMENSION})"
            )

    def normalize(
        self,
        left_path: Path,
        right_path: Path,
        output_left: Path,
        output_right: Path,
        target_w: int = 430,
        target_h: int = 480,
        bg_color: tuple[int, int, int, int] = (255, 255, 255, 0),
    ) -> tuple[Path, Path]:
        left = Image.open(left_path).convert("RGBA")
        right = Image.open(right_path).convert("RGBA")

        left_norm = self._fit_to_canvas(left, target_w, target_h, bg_color)
        right_norm = self._fit_to_canvas(right, target_w, target_h, bg_color)

        output_left.parent.mkdir(parents=True, exist_ok=True)
        output_right.parent.mkdir(parents=True, exist_ok=True)

        left_norm.save(str(output_left), format="PNG")
        right_norm.save(str(output_right), format="PNG")

        logger.info(
            f"Normalized images: left={output_left.name}, right={output_right.name}"
        )
        return output_left, output_right

    @staticmethod
    def _fit_to_canvas(
        image: Image.Image,
        target_w: int,
        target_h: int,
        bg_color: tuple[int, int, int, int],
    ) -> Image.Image:
        canvas = Image.new("RGBA", (target_w, target_h), bg_color)

        scale = min(target_w / image.width, target_h / image.height)
        new_w = max(1, int(image.width * scale))
        new_h = max(1, int(image.height * scale))
        resized = image.resize((new_w, new_h), Image.LANCZOS)

        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y), resized if resized.mode == "RGBA" else None)

        return canvas

    def create_comparison_canvas(
        self,
        left_path: Path,
        right_path: Path,
        output_path: Path,
    ) -> Path:
        left = Image.open(left_path).convert("RGBA")
        right = Image.open(right_path).convert("RGBA")

        half_w = COMPARISON_CANVAS_W // 2
        left_resized = self._fit_to_canvas(left, half_w, COMPARISON_CANVAS_H, (255, 255, 255, 0))
        right_resized = self._fit_to_canvas(right, half_w, COMPARISON_CANVAS_H, (255, 255, 255, 0))

        canvas = Image.new("RGBA", (COMPARISON_CANVAS_W, COMPARISON_CANVAS_H), (255, 255, 255, 0))
        canvas.paste(left_resized, (0, 0), left_resized)
        canvas.paste(right_resized, (half_w, 0), right_resized)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(output_path), format="PNG")
        logger.info(f"Comparison canvas saved: {output_path.name}")
        return output_path

    @staticmethod
    def remove_metadata(path: Path) -> None:
        img = Image.open(path)
        data = list(img.getdata())
        clean = Image.new(img.mode, img.size)
        clean.putdata(data)
        clean.save(str(path))

    @staticmethod
    def hash_content(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
