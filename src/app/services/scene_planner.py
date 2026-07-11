from __future__ import annotations

import logging
from typing import Optional

from app.domain.enums import Focus, ImageMotion, MascotPose, Transition
from app.domain.models import ScenePlan, ScriptPackage

logger = logging.getLogger(__name__)

_MIN_POSE_DURATION = 0.6
_MAX_SCENE_DURATION = 4.0
_MIN_SCENE_DURATION = 1.0


class ScenePlanner:
    def __init__(
        self,
        min_pose_duration: float = _MIN_POSE_DURATION,
        max_scene_duration: float = _MAX_SCENE_DURATION,
        min_scene_duration: float = _MIN_SCENE_DURATION,
    ):
        self.min_pose_duration = min_pose_duration
        self.max_scene_duration = max_scene_duration
        self.min_scene_duration = min_scene_duration

    def plan_from_script(self, script: ScriptPackage) -> list[ScenePlan]:
        if script.scenes:
            validated = self._validate_existing_scenes(script.scenes, script)
            if validated:
                return validated

        return self._auto_plan(script)

    def _validate_existing_scenes(
        self,
        scenes: list[ScenePlan],
        script: ScriptPackage,
    ) -> list[ScenePlan]:
        result: list[ScenePlan] = []
        last_pose: Optional[MascotPose] = None
        last_pose_end = 0.0
        cumulative_time = 0.0

        for scene in scenes:
            fixed = scene.model_copy()
            fixed.duration_hint_seconds = max(
                self.min_scene_duration,
                min(self.max_scene_duration, scene.duration_hint_seconds),
            )

            if last_pose == fixed.mascot_pose:
                if (cumulative_time - last_pose_end) < self.min_pose_duration:
                    pass
            else:
                if cumulative_time - last_pose_end < self.min_pose_duration and last_pose is not None:
                    logger.warning(
                        f"Pose switch too fast: {last_pose.value} -> "
                        f"{fixed.mascot_pose.value} at {cumulative_time:.1f}s"
                    )

            result.append(fixed)
            last_pose = fixed.mascot_pose
            last_pose_end = cumulative_time + fixed.duration_hint_seconds
            cumulative_time = last_pose_end

        return result

    def _auto_plan(self, script: ScriptPackage) -> list[ScenePlan]:
        sentences = self._split_sentences(script.narration_text)
        if not sentences:
            return []

        total_words = len(script.narration_text.split())
        target_duration = script.estimated_duration_seconds or 60.0
        words_per_second = total_words / target_duration if target_duration > 0 else 2.5

        scenes: list[ScenePlan] = []
        cumulative_time = 0.0
        left_item = script.title.split(" vs ")[0] if " vs " in script.title else "left"
        right_item = script.title.split(" vs ")[1] if " vs " in script.title else "right"

        for i, sentence in enumerate(sentences):
            word_count = len(sentence.split())
            duration = max(
                self.min_scene_duration,
                min(self.max_scene_duration, word_count / words_per_second),
            )

            pose = self._select_pose(
                sentence,
                i,
                len(sentences),
                left_item,
                right_item,
            )
            focus = self._select_focus(sentence, left_item, right_item, i, len(sentences))
            phrases = self._extract_phrases(sentence)
            transition = self._select_transition(i, len(sentences))
            motion = self._select_motion(i, len(sentences))
            emphasis = self._extract_emphasis(sentence)

            scenes.append(ScenePlan(
                index=i,
                narration=sentence,
                duration_hint_seconds=round(duration, 1),
                mascot_pose=pose,
                focus=focus,
                on_screen_phrases=phrases,
                transition=transition,
                image_motion=motion,
                emphasis=emphasis,
            ))
            cumulative_time += duration

        self._enforce_min_pose_duration(scenes)

        logger.info(
            f"Scene plan: {len(scenes)} scenes, "
            f"{cumulative_time:.1f}s total"
        )
        return scenes

    def _select_pose(
        self,
        sentence: str,
        index: int,
        total: int,
        left_item: str,
        right_item: str,
    ) -> MascotPose:
        lower = sentence.lower()

        if index == 0:
            return MascotPose.POINT_UP
        if index == total - 1:
            return MascotPose.THUMBS_UP

        if left_item.lower() in lower and right_item.lower() in lower:
            return MascotPose.PRESENT_BOTH

        if left_item.lower() in lower:
            return MascotPose.POINT_LEFT
        if right_item.lower() in lower:
            return MascotPose.POINT_RIGHT

        if any(w in lower for w in ("but", "however", "difference", "unlike", "versus")):
            return MascotPose.COMPARE_LEFT_RIGHT

        if any(w in lower for w in ("surprising", "actually", "wait", "did you know")):
            return MascotPose.SURPRISED

        if any(w in lower for w in ("think", "consider", "wonder")):
            return MascotPose.THINKING

        if any(w in lower for w in ("warning", "careful", "caution", "avoid", "danger")):
            return MascotPose.WARNING

        if any(w in lower for w in ("important", "key", "crucial", "remember")):
            return MascotPose.WARNING

        return MascotPose.NEUTRAL

    def _select_focus(
        self,
        sentence: str,
        left_item: str,
        right_item: str,
        index: int,
        total: int,
    ) -> Focus:
        if index == 0 or index == total - 1:
            return Focus.BOTH
        lower = sentence.lower()
        if left_item.lower() in lower and right_item.lower() in lower:
            return Focus.BOTH
        if left_item.lower() in lower:
            return Focus.LEFT
        if right_item.lower() in lower:
            return Focus.RIGHT
        return Focus.NEUTRAL

    def _extract_phrases(self, sentence: str) -> list[str]:
        words = sentence.split()
        if not words:
            return []

        if len(words) <= 3:
            return [sentence.upper().strip(".,!?")]

        key_sentence = words[:3]
        phrase = " ".join(key_sentence).upper().strip(".,!?")
        if len(phrase) > 42:
            phrase = phrase[:42]
        return [phrase]

    def _select_transition(self, index: int, total: int) -> Transition:
        if index == 0:
            return Transition.FADE
        if index == total - 1:
            return Transition.FADE
        if index % 3 == 0:
            return Transition.CROSSFADE
        return Transition.QUICK_FADE

    def _select_motion(self, index: int, total: int) -> ImageMotion:
        motions = [
            ImageMotion.SLOW_ZOOM_IN,
            ImageMotion.SLOW_ZOOM_IN,
            ImageMotion.SLOW_PAN_RIGHT,
            ImageMotion.SLOW_ZOOM_OUT,
            ImageMotion.SLOW_PAN_LEFT,
            ImageMotion.PULSE,
        ]
        return motions[index % len(motions)]

    def _extract_emphasis(self, sentence: str) -> list[str]:
        emphasis: list[str] = []
        words = sentence.split()
        for word in words:
            clean = word.strip(".,!?;:\"'")
            if len(clean) >= 5 and clean[0].isupper():
                emphasis.append(clean)
        return emphasis[:3]

    def _enforce_min_pose_duration(self, scenes: list[ScenePlan]) -> None:
        for i in range(1, len(scenes)):
            if scenes[i].mascot_pose != scenes[i - 1].mascot_pose:
                if scenes[i - 1].duration_hint_seconds < self.min_pose_duration:
                    extra = self.min_pose_duration - scenes[i - 1].duration_hint_seconds
                    scenes[i - 1].duration_hint_seconds = round(
                        scenes[i - 1].duration_hint_seconds + extra, 1
                    )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        import re

        parts = re.split(r"[.!?]+\s*", text)
        return [p.strip() for p in parts if p.strip()]
