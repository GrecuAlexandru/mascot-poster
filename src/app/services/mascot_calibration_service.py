from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, model_validator


class CanvasSpec(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PivotSpec(BaseModel):
    x: float
    y: float


class ReferenceDot(PivotSpec):
    radius: int = Field(default=9, gt=0)
    color: tuple[int, int, int, int] = (255, 0, 90, 255)


class PoseCalibration(PivotSpec):
    scale: float = Field(default=1.0, gt=0.1, le=3.0)


class MascotCalibration(BaseModel):
    canvas: CanvasSpec
    reference_dot: ReferenceDot
    source_pivot: PivotSpec
    base_render_height: int = Field(gt=0)
    poses: dict[str, PoseCalibration]

    @model_validator(mode="after")
    def validate_coordinates(self) -> "MascotCalibration":
        points = [self.reference_dot, *self.poses.values()]
        for point in points:
            if not 0 <= point.x < self.canvas.width:
                raise ValueError(f"x coordinate outside canvas: {point.x}")
            if not 0 <= point.y < self.canvas.height:
                raise ValueError(f"y coordinate outside canvas: {point.y}")
        return self


class MascotCalibrationService:
    def __init__(self, mascot_dir: Path, config_path: Optional[Path] = None):
        self.mascot_dir = Path(mascot_dir)
        self.meta_path = self.mascot_dir / "mascot_meta.json"
        self.config_path = config_path or self.mascot_dir / "pose_calibration.json"
        self._meta = self._load_meta()

    def load(self) -> MascotCalibration:
        if not self.config_path.exists():
            raise FileNotFoundError(self.config_path)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        calibration = MascotCalibration.model_validate(payload)
        self.validate_pose_set(calibration)
        return calibration

    def validate_pose_set(self, calibration: MascotCalibration) -> None:
        declared = set(self._meta.get("poses", {}))
        configured = set(calibration.poses)
        missing = sorted(declared - configured)
        extra = sorted(configured - declared)
        if missing:
            raise ValueError("Missing pose calibration: " + ", ".join(missing))
        if extra:
            raise ValueError("Unknown pose calibration: " + ", ".join(extra))
        for pose, filename in self._meta.get("poses", {}).items():
            if not (self.mascot_dir / filename).exists():
                raise FileNotFoundError(f"Mascot pose not found: {pose}")

    def render_pose(
        self,
        pose: str,
        show_reference_dot: bool,
        pose_calibration: Optional[PoseCalibration] = None,
    ) -> Image.Image:
        calibration = self.load()
        selected = pose_calibration or calibration.poses[pose]
        canvas = Image.new(
            "RGBA",
            (calibration.canvas.width, calibration.canvas.height),
            (255, 255, 255, 255),
        )
        self.paste_calibrated_pose(canvas, pose, selected, calibration)
        ImageDraw.Draw(canvas).text((32, 32), pose, fill=(20, 20, 20, 255))
        if show_reference_dot:
            self.draw_reference_dot(canvas, calibration.reference_dot)
        return canvas

    def render_all(self, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, Path] = {}
        for pose in self.load().poses:
            path = output_dir / f"{pose}.png"
            self.render_pose(pose, show_reference_dot=True).save(path)
            outputs[pose] = path
        return outputs

    def paste_calibrated_pose(
        self,
        canvas: Image.Image,
        pose: str,
        pose_calibration: PoseCalibration,
        calibration: Optional[MascotCalibration] = None,
        extra_scale: float = 1.0,
        anchor_offset_x: float = 0.0,
    ) -> tuple[int, int, int, int]:
        calibration = calibration or self.load()
        source = self._pose_image(pose)
        height = max(1, round(calibration.base_render_height * pose_calibration.scale * extra_scale))
        width = max(1, round(source.width * height / source.height))
        resized = source.resize((width, height), Image.Resampling.LANCZOS)
        pivot_x = calibration.source_pivot.x * width / source.width
        pivot_y = calibration.source_pivot.y * height / source.height
        paste_x = round(pose_calibration.x + anchor_offset_x - pivot_x)
        paste_y = round(pose_calibration.y - pivot_y)
        canvas.alpha_composite(resized, (paste_x, paste_y))
        return paste_x, paste_y, width, height

    @staticmethod
    def draw_reference_dot(canvas: Image.Image, dot: ReferenceDot) -> None:
        draw = ImageDraw.Draw(canvas)
        draw.ellipse(
            (
                round(dot.x - dot.radius),
                round(dot.y - dot.radius),
                round(dot.x + dot.radius),
                round(dot.y + dot.radius),
            ),
            fill=dot.color,
        )

    def _load_meta(self) -> dict:
        if not self.meta_path.exists():
            raise FileNotFoundError(self.meta_path)
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _pose_image(self, pose: str) -> Image.Image:
        filename = self._meta.get("poses", {}).get(pose)
        if filename is None:
            raise ValueError(f"Unknown mascot pose: {pose}")
        return Image.open(self.mascot_dir / filename).convert("RGBA")
