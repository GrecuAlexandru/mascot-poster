from __future__ import annotations

from app.domain.enums import MascotPose
from app.domain.models import DirectionPlan, ReferenceScriptPackage
from app.services.reference_direction_validator import ReferenceDirectionValidator


class ReferenceDirectionService:
    def __init__(self, llm: object, validator: ReferenceDirectionValidator | None = None):
        self.llm = llm
        self.validator = validator or ReferenceDirectionValidator()

    async def generate(
        self,
        script: ReferenceScriptPackage,
        language: str,
    ) -> DirectionPlan:
        beat_lines = []
        for beat in script.all_beats:
            words = beat.text.split()
            indexed = ", ".join(f"{index}:{word}" for index, word in enumerate(words))
            beat_lines.append(f"{beat.id}: {indexed}")
        system = (
            "You are the visual director for a reference-style short-form comparison video. "
            "Return only expressive beat-level mascot, product-focus, and sound-effect cues."
        )
        user = (
            f"Language: {language}. Available poses: {', '.join(pose.value for pose in MascotPose)}. "
            "Always use mascot_anchor center so the calibrated feet never move. Use product_focus left, "
            "right, both, or neutral. Use point_left or point_up_left with left focus and point_right or "
            "point_up_right with right focus. Use varied expressive poses for hook, explanation, warning, "
            "idea, and conclusion beats. Use one cue per beat and never more than two. Use pose_pop for "
            "pose swaps and focus_tick for focus-only changes. Never return an all-neutral plan.\nBeat words:\n"
            f"{chr(10).join(beat_lines)}"
        )
        plan = await self.llm.complete_structured(
            system,
            user,
            DirectionPlan,
            schema_name="reference_direction",
            temperature=0.2,
            max_tokens=2200,
        )
        normalized = self.validator.normalize(plan)
        problems = self.validator.validate(normalized, script)
        if not problems:
            return normalized
        repaired = await self.llm.complete_structured(
            system,
            user + "\nRepair these exact problems: " + "; ".join(problems),
            DirectionPlan,
            schema_name="reference_direction_repair",
            temperature=0.0,
            max_tokens=2200,
        )
        normalized = self.validator.normalize(repaired)
        if not self.validator.validate(normalized, script):
            return normalized
        return self.validator.fallback(script)
