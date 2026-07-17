from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageFilter
from pydantic import BaseModel, Field


class ProductAssetMetrics(BaseModel):
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    visible_bbox: tuple[int, int, int, int]
    visible_width: int = Field(gt=0)
    visible_height: int = Field(gt=0)
    width_occupancy: float = Field(ge=0.0, le=1.0)
    height_occupancy: float = Field(ge=0.0, le=1.0)
    major_axis_occupancy: float = Field(ge=0.0, le=1.0)
    normalized_width: int = Field(gt=0)
    normalized_height: int = Field(gt=0)
    detection_mode: Literal["alpha", "non_white", "opaque_white"]


class ProductAssetNormalizer:
    def __init__(
        self,
        non_white_threshold: int = 32,
        alpha_threshold: int = 16,
        padding_pixels: int = 6,
        minimum_major_axis_occupancy: float = 0.55,
    ):
        self.non_white_threshold = non_white_threshold
        self.alpha_threshold = alpha_threshold
        self.padding_pixels = padding_pixels
        self.minimum_major_axis_occupancy = minimum_major_axis_occupancy

    def normalize(self, source: Path, output: Path) -> ProductAssetMetrics:
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
        cropped, metrics = self.crop_visible_subject(image, enforce_minimum=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output, format="PNG")
        return metrics

    def crop_visible_subject(
        self,
        image: Image.Image,
        enforce_minimum: bool = False,
    ) -> tuple[Image.Image, ProductAssetMetrics]:
        rgba = image.convert("RGBA")
        prepared, mask, mode = self._prepare_visible_subject(rgba)
        bbox = mask.getbbox()
        if bbox is None:
            raise ValueError("Product image contains no visible subject pixels")
        visible_width = bbox[2] - bbox[0]
        visible_height = bbox[3] - bbox[1]
        width_occupancy = visible_width / rgba.width
        height_occupancy = visible_height / rgba.height
        major_axis_occupancy = max(width_occupancy, height_occupancy)
        if enforce_minimum and major_axis_occupancy < self.minimum_major_axis_occupancy:
            percentage = round(self.minimum_major_axis_occupancy * 100)
            raise ValueError(f"Product subject must occupy at least {percentage}% of the source canvas")
        padded = (
            max(0, bbox[0] - self.padding_pixels),
            max(0, bbox[1] - self.padding_pixels),
            min(rgba.width, bbox[2] + self.padding_pixels),
            min(rgba.height, bbox[3] + self.padding_pixels),
        )
        cropped = prepared.crop(padded)
        metrics = ProductAssetMetrics(
            source_width=rgba.width,
            source_height=rgba.height,
            visible_bbox=bbox,
            visible_width=visible_width,
            visible_height=visible_height,
            width_occupancy=width_occupancy,
            height_occupancy=height_occupancy,
            major_axis_occupancy=major_axis_occupancy,
            normalized_width=cropped.width,
            normalized_height=cropped.height,
            detection_mode=mode,
        )
        return cropped, metrics

    def _prepare_visible_subject(
        self,
        image: Image.Image,
    ) -> tuple[
        Image.Image,
        Image.Image,
        Literal["alpha", "non_white", "opaque_white"],
    ]:
        alpha = image.getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        if alpha_min < self.alpha_threshold <= alpha_max:
            mask = alpha.point(
                lambda value: 255 if value >= self.alpha_threshold else 0,
            )
            return image, mask, "alpha"
        background = self._edge_connected_background_mask(image)
        if background is None:
            mask = self._non_white_mask(image)
            return image, mask, "non_white"
        subject = self._remove_perimeter_seams(ImageChops.invert(background))
        bbox = subject.getbbox()
        if bbox is not None:
            subject_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            coverage = sum(
                value > 0
                for value in subject.crop(bbox).get_flattened_data()
            ) / subject_area
            if coverage < 0.5:
                return self._opaque_white_subject(image), subject, "opaque_white"
        background = ImageChops.invert(subject)
        softened = ImageChops.invert(
            background.filter(ImageFilter.GaussianBlur(radius=0.75)),
        )
        softened = ImageChops.lighter(subject, softened)
        prepared = image.copy()
        prepared.putalpha(ImageChops.multiply(alpha, softened))
        return prepared, subject, "non_white"

    @staticmethod
    def _opaque_white_subject(image: Image.Image) -> Image.Image:
        prepared = image.copy()
        prepared.putalpha(255)
        return prepared

    def _edge_connected_background_mask(self, image: Image.Image) -> Image.Image | None:
        rgb = image.convert("RGB")
        pixels = list(rgb.get_flattened_data())
        width, height = rgb.size
        border_indices = [*range(width), *range((height - 1) * width, height * width)]
        border_indices.extend(row * width for row in range(1, height - 1))
        border_indices.extend(row * width + width - 1 for row in range(1, height - 1))
        light_border = [
            pixels[index]
            for index in border_indices
            if min(pixels[index]) >= 220
            and max(pixels[index]) - min(pixels[index]) <= 40
        ]
        if len(light_border) < len(border_indices) * 0.6:
            return None
        background = tuple(
            sorted(pixel[channel] for pixel in light_border)[len(light_border) // 2]
            for channel in range(3)
        )
        color_distance = self.non_white_threshold + 28
        candidates = bytearray(
            1
            if min(pixel) >= 190
            and max(pixel) - min(pixel) <= 56
            and max(abs(pixel[channel] - background[channel]) for channel in range(3))
            <= color_distance
            else 0
            for pixel in pixels
        )
        connected = bytearray(width * height)
        queue: deque[int] = deque()

        def seed(index: int) -> None:
            if candidates[index] and not connected[index]:
                connected[index] = 255
                queue.append(index)

        for index in border_indices:
            seed(index)
        while queue:
            index = queue.popleft()
            x = index % width
            if x > 0:
                seed(index - 1)
            if x + 1 < width:
                seed(index + 1)
            if index >= width:
                seed(index - width)
            if index + width < len(connected):
                seed(index + width)
        mask = Image.new("L", (width, height))
        mask.frombytes(bytes(connected))
        return mask

    @staticmethod
    def _remove_perimeter_seams(subject: Image.Image) -> Image.Image:
        width, height = subject.size
        pixels = bytearray(subject.tobytes())
        visited = bytearray(len(pixels))
        cleaned = bytearray(pixels)
        perimeter_distance = max(6, round(min(width, height) * 0.02))
        maximum_vertical_width = max(2, round(width * 0.01))
        maximum_horizontal_height = max(2, round(height * 0.01))

        for start, value in enumerate(pixels):
            if not value or visited[start]:
                continue
            queue: deque[int] = deque([start])
            visited[start] = 1
            component: list[int] = []
            min_x = width
            max_x = 0
            min_y = height
            max_y = 0
            while queue:
                index = queue.popleft()
                component.append(index)
                x = index % width
                y = index // width
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                neighbors = []
                if x > 0:
                    neighbors.append(index - 1)
                if x + 1 < width:
                    neighbors.append(index + 1)
                if y > 0:
                    neighbors.append(index - width)
                if y + 1 < height:
                    neighbors.append(index + width)
                for neighbor in neighbors:
                    if pixels[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        queue.append(neighbor)
            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            near_perimeter = (
                min_x <= perimeter_distance
                or min_y <= perimeter_distance
                or max_x >= width - perimeter_distance - 1
                or max_y >= height - perimeter_distance - 1
            )
            vertical_seam = (
                component_width <= maximum_vertical_width
                and component_height >= height * 0.5
            )
            horizontal_seam = (
                component_height <= maximum_horizontal_height
                and component_width >= width * 0.5
            )
            small_seam = (
                len(component) <= max(24, round(width * height * 0.002))
                and (
                    component_width <= maximum_vertical_width
                    or component_height <= maximum_horizontal_height
                )
            )
            if near_perimeter and (vertical_seam or horizontal_seam or small_seam):
                for index in component:
                    cleaned[index] = 0
        result = Image.new("L", (width, height))
        result.frombytes(bytes(cleaned))
        return result

    def _non_white_mask(self, image: Image.Image) -> Image.Image:
        alpha = image.getchannel("A")
        white = Image.new("RGB", image.size, (255, 255, 255))
        composited = Image.new("RGB", image.size, (255, 255, 255))
        composited.paste(image.convert("RGB"), mask=alpha)
        difference = ImageChops.difference(composited, white)
        red, green, blue = difference.split()
        distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        return distance.point(
            lambda value: 255 if value > self.non_white_threshold else 0,
        )
