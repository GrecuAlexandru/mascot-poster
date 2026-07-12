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
            f"On screen, the LEFT side shows '{script.left_item}' and the RIGHT side shows "
            f"'{script.right_item}'. Directions are from the viewer's perspective: when a beat talks "
            "about the left-side item use product_focus left, and when it talks about the right-side "
            "item use product_focus right. "
            "Always use mascot_anchor center so the calibrated feet never move. Use product_focus left, "
            "right, both, or neutral. For left focus use point_up_left and for right focus use "
            "point_up_right, so the mascot looks up toward the item it talks about. Use varied "
            "expressive poses for hook, explanation, warning, "
            "idea, and conclusion beats. When one beat discusses BOTH products, return exactly two cues: "
            "one on the first word naming the left product with point_up_left and left focus, then one on "
            "the first word naming the right product with point_up_right and right focus. Example: for "
            "'Coffee is bitter. Tea is mild.' return Coffee/point_up_left/left and Tea/point_up_right/right. "
            "Incorrect: one left cue for the whole beat. Incorrect: repeating point_up_left across several "
            "beats that also describe the right product. For a one-sided beat, use one cue; never use more "
            "than two cues per non-hook beat. Use pose_pop for "
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
        normalized = self.validator.normalize(
            self.validator.align_with_script(plan, script)
        )
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
        normalized = self.validator.normalize(
            self.validator.align_with_script(repaired, script)
        )
        if not self.validator.validate(normalized, script):
            return normalized
        return self.validator.fallback(script)
