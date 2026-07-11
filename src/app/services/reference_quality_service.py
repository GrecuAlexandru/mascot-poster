from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.domain.enums import MascotAnchor, MascotPose
from app.domain.models import CompiledVideoSpec, RenderResult


class ReferenceQualityService:
    def __init__(self, media_quality_service: object):
        self.media_quality_service = media_quality_service

    def validate(self, spec: CompiledVideoSpec, result: RenderResult) -> list[str]:
        problems = list(self.media_quality_service.validate_video(result.video_path))
        problems.extend(self.media_quality_service.validate_content(result, len(spec.direction_cues)))
        if not 20.0 <= spec.transcript.duration_seconds <= 60.0:
            problems.append(
                f"Narration duration {spec.transcript.duration_seconds:.1f}s outside 20-60 second target"
            )
        if abs(result.duration_seconds - spec.total_duration_seconds) > 1.0 / spec.fps:
            problems.append(
                f"Final duration {result.duration_seconds:.3f}s does not match "
                f"compiled duration {spec.total_duration_seconds:.3f}s"
            )
        if spec.template != "reference_v1":
            problems.append("Reference render must use reference_v1")
        if any("tests/fixtures" in str(path).replace("\\", "/") for path in (spec.left_image, spec.right_image)):
            problems.append("Production render uses fixture image asset")
        problems.extend(self._caption_problems(spec))
        problems.extend(self._sfx_problems(spec))
        problems.extend(self._direction_problems(spec))
        problems.extend(self._visual_problems(result.poster_path))
        return problems

    @staticmethod
    def _caption_problems(spec: CompiledVideoSpec) -> list[str]:
        spoken = [word.word for word in spec.transcript.words]
        active = [cue.words[cue.active_word_index] for cue in spec.captions]
        if active != spoken:
            return ["Caption active-word sequence does not match narration"]
        return []

    @staticmethod
    def _sfx_problems(spec: CompiledVideoSpec) -> list[str]:
        previous = -1.0
        for cue in spec.sound_cues:
            if cue.kind.value == "cta_sting":
                continue
            if cue.start < previous + 0.6:
                return ["SFX cues are closer than 600 ms"]
            previous = cue.start
        return []

    @staticmethod
    def _visual_problems(poster_path: Path) -> list[str]:
        if not poster_path.exists():
            return ["Poster frame not found"]
        image = Image.open(poster_path).convert("RGB")
        corners = [
            image.getpixel((0, 0)),
            image.getpixel((image.width - 1, 0)),
            image.getpixel((0, image.height - 1)),
            image.getpixel((image.width - 1, image.height - 1)),
        ]
        if any(min(pixel) < 240 for pixel in corners):
            return ["Reference poster background is not white"]
        return []

    @staticmethod
    def _direction_problems(spec: CompiledVideoSpec) -> list[str]:
        if any(cue.mascot_anchor != MascotAnchor.CENTER for cue in spec.direction_cues):
            return ["Reference mascot direction changes its calibrated anchor"]
        if spec.direction_cues and all(
            cue.mascot_pose == MascotPose.NEUTRAL for cue in spec.direction_cues
        ):
            return ["Reference mascot direction uses only the neutral pose"]
        return []
