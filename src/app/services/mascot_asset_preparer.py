from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


class MascotAssetPreparer:
    def __init__(
        self,
        canvas_size: tuple[int, int] = (768, 768),
        padding: int = 24,
        tolerance: int = 24,
    ):
        self.canvas_size = canvas_size
        self.padding = padding
        self.tolerance = tolerance

    def prepare(self, source: Path, destination: Path) -> Path:
        image = Image.open(source).convert("RGBA")
        foreground_mask = self._foreground_mask(image)
        feathered = foreground_mask.filter(ImageFilter.GaussianBlur(radius=0.6))
        alpha = ImageChops.multiply(image.getchannel("A"), feathered)
        image.putalpha(alpha)

        threshold = alpha.point(lambda value: 255 if value >= 16 else 0)
        bounds = threshold.getbbox()
        if bounds is None:
            raise ValueError(f"No mascot foreground detected in {source}")
        cropped = image.crop(bounds)

        canvas_width, canvas_height = self.canvas_size
        max_width = canvas_width - self.padding * 2
        max_height = canvas_height - self.padding * 2
        scale = min(max_width / cropped.width, max_height / cropped.height)
        size = (
            max(1, round(cropped.width * scale)),
            max(1, round(cropped.height * scale)),
        )
        resized = cropped.resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", self.canvas_size, (255, 255, 255, 0))
        x = (canvas_width - resized.width) // 2
        y = canvas_height - self.padding - resized.height
        canvas.alpha_composite(resized, (x, y))

        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(destination, format="PNG")
        return destination

    def _foreground_mask(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        raw = image.tobytes()

        def color(index: int) -> tuple[int, int, int, int]:
            start = index * 4
            return raw[start], raw[start + 1], raw[start + 2], raw[start + 3]

        corner_colors = [
            color(0)[:3],
            color(width - 1)[:3],
            color((height - 1) * width)[:3],
            color(width * height - 1)[:3],
        ]
        background = tuple(
            round(sum(color[channel] for color in corner_colors) / len(corner_colors))
            for channel in range(3)
        )
        connected_background = bytearray(width * height)
        queue: deque[int] = deque()

        def qualifies(index: int) -> bool:
            red, green, blue, opacity = color(index)
            return opacity > 0 and max(
                abs(red - background[0]),
                abs(green - background[1]),
                abs(blue - background[2]),
            ) <= self.tolerance

        def add(index: int) -> None:
            if not connected_background[index] and qualifies(index):
                connected_background[index] = 1
                queue.append(index)

        for x in range(width):
            add(x)
            add((height - 1) * width + x)
        for y in range(height):
            add(y * width)
            add(y * width + width - 1)

        while queue:
            index = queue.popleft()
            x = index % width
            y = index // width
            if x > 0:
                add(index - 1)
            if x + 1 < width:
                add(index + 1)
            if y > 0:
                add(index - width)
            if y + 1 < height:
                add(index + width)

        mask = Image.new("L", (width, height), 255)
        mask.putdata([0 if connected else 255 for connected in connected_background])
        return mask
