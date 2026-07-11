from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PIL import Image

from app.domain.exceptions import MascotAssetError
from app.domain.models import MascotPose


class MascotService:
    def __init__(self, mascot_dir: Path):
        self.mascot_dir = mascot_dir
        self._meta: dict = {}
        self._load_meta()

    def _load_meta(self) -> None:
        meta_path = self.mascot_dir / "mascot_meta.json"
        if meta_path.exists():
            self._meta = json.loads(meta_path.read_text(encoding="utf-8"))

    @property
    def set_name(self) -> str:
        if self._meta:
            return self._meta.get("set_name", self.mascot_dir.name)
        return self.mascot_dir.name

    @property
    def canvas_size(self) -> tuple[int, int]:
        if self._meta:
            return (
                self._meta.get("canvas_width", 1024),
                self._meta.get("canvas_height", 1024),
            )
        return (1024, 1024)

    @property
    def available_poses(self) -> list[str]:
        if self._meta and "poses" in self._meta:
            return list(self._meta["poses"].keys())
        return [
            p.stem for p in self.mascot_dir.glob("*.png")
            if not p.name.startswith(".")
        ]

    def pose_path(self, pose: str) -> Optional[Path]:
        if "poses" in self._meta and pose in self._meta["poses"]:
            return self.mascot_dir / self._meta["poses"][pose]
        candidate = self.mascot_dir / f"{pose}.png"
        if candidate.exists():
            return candidate
        return None

    def validate_poses(self, required: list[str]) -> list[str]:
        missing: list[str] = []
        for pose in required:
            path = self.pose_path(pose)
            if path is None or not path.exists():
                missing.append(pose)
        return missing

    def validate_pose_images(self, poses: list[str]) -> list[str]:
        problems: list[str] = []
        for pose in poses:
            path = self.pose_path(pose)
            if path is None or not path.exists():
                continue
            try:
                img = Image.open(path)
                if img.mode != "RGBA":
                    problems.append(f"Pose '{pose}' is not RGBA (got {img.mode})")
                else:
                    alpha = img.getchannel("A")
                    alpha_min, alpha_max = alpha.getextrema()
                    if alpha_min != 0 or alpha_max == 0:
                        problems.append(
                            f"Pose '{pose}' must contain visible pixels and transparent background"
                        )
                    border = bytearray(alpha.crop((0, 0, img.width, 1)).tobytes())
                    border.extend(alpha.crop((0, img.height - 1, img.width, img.height)).tobytes())
                    border.extend(alpha.crop((0, 0, 1, img.height)).tobytes())
                    border.extend(alpha.crop((img.width - 1, 0, img.width, img.height)).tobytes())
                    if any(value > 0 for value in border):
                        problems.append(f"Pose '{pose}' border is not transparent")
                cw, ch = self.canvas_size
                if img.size != (cw, ch):
                    problems.append(
                        f"Pose '{pose}' size {img.size} != canvas {(cw, ch)}"
                    )
            except Exception as e:
                problems.append(f"Pose '{pose}' failed to load: {e}")
        return problems
