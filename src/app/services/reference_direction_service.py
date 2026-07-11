from __future__ import annotations

from app.domain.enums import MascotPose
from app.domain.models import DirectionPlan, ReferenceScriptPackage


class ReferenceDirectionService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        script: ReferenceScriptPackage,
        language: str,
    ) -> DirectionPlan:
        beat_lines = []
        for beat in script.beats:
            words = beat.text.split()
            indexed = ", ".join(f"{index}:{word}" for index, word in enumerate(words))
            beat_lines.append(f"{beat.id}: {indexed}")
        system = (
            "You are the visual director for a reference-style short-form comparison video. "
            "Return only word-anchored mascot, product-focus, and sound-effect cues."
        )
        user = (
            f"Language: {language}. Available poses: {', '.join(pose.value for pose in MascotPose)}. "
            "Use mascot_anchor left, center, or right. Use product_focus left, right, both, or neutral. "
            "Use whoosh for mascot anchor changes, pose_pop for pose-only swaps, focus_tick for product focus, "
            "and avoid more than one cue per spoken word.\nBeat words:\n"
            f"{chr(10).join(beat_lines)}"
        )
        return await self.llm.complete_structured(
            system,
            user,
            DirectionPlan,
            schema_name="reference_direction",
            temperature=0.2,
            max_tokens=2200,
        )
