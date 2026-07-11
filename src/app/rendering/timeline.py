from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain.models import SceneSpec


@dataclass
class TimelineEntry:
    scene_index: int
    scene: SceneSpec
    frame_path: Path | None = None
    segment_path: Path | None = None
    segment_duration: float = 0.0


@dataclass
class Timeline:
    entries: list[TimelineEntry]
    total_duration: float
    fps: int

    @property
    def total_frames(self) -> int:
        return int(self.total_duration * self.fps)

    @classmethod
    def from_scenes(cls, scenes: list[SceneSpec], fps: int) -> "Timeline":
        entries = [
            TimelineEntry(scene_index=i, scene=s) for i, s in enumerate(scenes)
        ]
        total = scenes[-1].end - scenes[0].start if scenes else 0.0
        return cls(entries=entries, total_duration=total, fps=fps)

    def to_dict(self) -> dict:
        return {
            "total_duration_seconds": round(self.total_duration, 3),
            "total_frames": self.total_frames,
            "fps": self.fps,
            "scenes": [
                {
                    "index": e.scene_index,
                    "start": e.scene.start,
                    "end": e.scene.end,
                    "duration": e.scene.duration,
                    "pose": e.scene.pose.value,
                    "phrase": e.scene.phrase,
                    "focus": e.scene.focus.value,
                    "image_motion": e.scene.image_motion.value,
                    "transition": e.scene.transition.value,
                    "frame_path": str(e.frame_path) if e.frame_path else None,
                    "segment_path": str(e.segment_path) if e.segment_path else None,
                }
                for e in self.entries
            ],
        }
