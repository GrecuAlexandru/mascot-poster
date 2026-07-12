from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.domain.enums import Focus, MascotAnchor, MascotPose, SfxKind
from app.domain.models import DirectionCue, DirectionPlan, ReferenceScriptPackage


class ReferenceDirectionValidator:
    left_poses = {MascotPose.POINT_LEFT, MascotPose.POINT_UP_LEFT}
    right_poses = {MascotPose.POINT_RIGHT, MascotPose.POINT_UP_RIGHT}
    mirror_poses = {
        MascotPose.POINT_LEFT: MascotPose.POINT_RIGHT,
        MascotPose.POINT_RIGHT: MascotPose.POINT_LEFT,
        MascotPose.POINT_UP_LEFT: MascotPose.POINT_UP_RIGHT,
        MascotPose.POINT_UP_RIGHT: MascotPose.POINT_UP_LEFT,
    }

    def align_with_script(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
    ) -> DirectionPlan:
        left_key = self._item_key(script.left_item)
        right_key = self._item_key(script.right_item)
        beat_texts = {beat.id: beat.text.casefold() for beat in script.all_beats}
        cues: list[DirectionCue] = []
        for cue in plan.cues:
            text = beat_texts.get(cue.beat_id, "")
            mentions_left = bool(left_key) and left_key in text
            mentions_right = bool(right_key) and right_key in text
            if mentions_left == mentions_right:
                cues.append(cue)
                continue
            side = Focus.LEFT if mentions_left else Focus.RIGHT
            wrong_poses = self.right_poses if side == Focus.LEFT else self.left_poses
            update: dict = {}
            if cue.product_focus in (Focus.LEFT, Focus.RIGHT) and cue.product_focus != side:
                update["product_focus"] = side
            if cue.mascot_pose in wrong_poses:
                update["mascot_pose"] = self.mirror_poses[cue.mascot_pose]
            cues.append(cue.model_copy(update=update) if update else cue)
        balanced = self._enforce_comparison_cues(DirectionPlan(cues=cues), script)
        return self._enforce_hook_cues(balanced, script)

    def _enforce_comparison_cues(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
    ) -> DirectionPlan:
        replacements: dict[str, list[DirectionCue]] = {}
        for beat in script.beats:
            if beat.id == "hook":
                continue
            words = self._tokens(beat.text)
            left_words = self._tokens(script.left_item)
            right_words = self._tokens(script.right_item)
            left_start = self._find_item(words, left_words, right_words)
            right_start = self._find_item(words, right_words, left_words)
            if left_start is None or right_start is None or left_start == right_start:
                continue
            replacements[beat.id] = sorted(
                [
                    DirectionCue(
                        beat_id=beat.id,
                        word_index=left_start,
                        mascot_pose=MascotPose.POINT_UP_LEFT,
                        mascot_anchor=MascotAnchor.CENTER,
                        product_focus=Focus.LEFT,
                    ),
                    DirectionCue(
                        beat_id=beat.id,
                        word_index=right_start,
                        mascot_pose=MascotPose.POINT_UP_RIGHT,
                        mascot_anchor=MascotAnchor.CENTER,
                        product_focus=Focus.RIGHT,
                    ),
                ],
                key=lambda cue: cue.word_index,
            )
        result: list[DirectionCue] = []
        known_ids = {beat.id for beat in script.all_beats}
        for beat in script.all_beats:
            if beat.id in replacements:
                result.extend(replacements[beat.id])
            else:
                result.extend(cue for cue in plan.cues if cue.beat_id == beat.id)
        result.extend(cue for cue in plan.cues if cue.beat_id not in known_ids)
        return DirectionPlan(cues=result)

    def _enforce_hook_cues(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
    ) -> DirectionPlan:
        hook = next((beat for beat in script.all_beats if beat.id == "hook"), None)
        if hook is None:
            return plan
        words = self._tokens(hook.text)
        left_words = self._tokens(script.left_item)
        right_words = self._tokens(script.right_item)
        left_start = self._find_phrase(words, left_words)
        right_start = self._find_phrase(words, right_words, (left_start or 0) + len(left_words))
        if left_start is None or right_start is None:
            return plan
        question_start = next(
            (
                index
                for index in range(right_start + len(right_words), len(words))
                if words[index] in {"dar", "but"}
            ),
            right_start + len(right_words),
        )
        hook_cues = [
            DirectionCue(
                beat_id="hook",
                word_index=left_start,
                mascot_pose=MascotPose.POINT_UP_LEFT,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.LEFT,
            ),
            DirectionCue(
                beat_id="hook",
                word_index=right_start,
                mascot_pose=MascotPose.POINT_UP_RIGHT,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.RIGHT,
            ),
            DirectionCue(
                beat_id="hook",
                word_index=question_start,
                mascot_pose=MascotPose.INTRO_HANDS_UP,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.BOTH,
            ),
        ]
        return DirectionPlan(cues=[*hook_cues, *(cue for cue in plan.cues if cue.beat_id != "hook")])

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = unicodedata.normalize("NFKD", text.casefold())
        without_marks = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return re.findall(r"\w+", without_marks)

    @classmethod
    def _find_item(
        cls,
        words: list[str],
        item_words: list[str],
        opposing_words: list[str],
    ) -> int | None:
        exact = cls._find_phrase(words, item_words)
        if exact is not None:
            return exact
        distinctive = [
            word
            for word in item_words
            if word not in opposing_words and len(word) >= 3
        ]
        for index, word in enumerate(words):
            if any(cls._token_matches(word, candidate) for candidate in distinctive):
                return index
        return None

    @staticmethod
    def _token_matches(word: str, candidate: str) -> bool:
        if word == candidate:
            return True
        common_length = min(len(word), len(candidate))
        return common_length >= 4 and word[:common_length - 1] == candidate[:common_length - 1]

    @staticmethod
    def _find_phrase(words: list[str], phrase: list[str], start: int = 0) -> int | None:
        if not phrase:
            return None
        for index in range(start, len(words) - len(phrase) + 1):
            if words[index:index + len(phrase)] == phrase:
                return index
        return None

    @staticmethod
    def _item_key(item: str) -> str:
        head = re.split(r"[:,(–—]", item, maxsplit=1)[0]
        key = head.casefold().strip()
        return key if len(key) >= 3 else ""

    # The mascot points up-and-to-the-side so it looks toward the item it discusses.
    _prefer_up = {
        MascotPose.POINT_LEFT: MascotPose.POINT_UP_LEFT,
        MascotPose.POINT_RIGHT: MascotPose.POINT_UP_RIGHT,
    }

    def normalize(self, plan: DirectionPlan) -> DirectionPlan:
        result: list[DirectionCue] = []
        previous: DirectionCue | None = None
        for cue in plan.cues:
            pose = self._prefer_up.get(cue.mascot_pose, cue.mascot_pose)
            normalized = cue.model_copy(update={
                "mascot_anchor": MascotAnchor.CENTER,
                "mascot_pose": pose,
            })
            if previous is None or normalized.mascot_pose != previous.mascot_pose:
                sfx = SfxKind.POSE_POP
            elif normalized.product_focus != previous.product_focus:
                sfx = SfxKind.FOCUS_TICK
            else:
                sfx = SfxKind.NONE
            normalized = normalized.model_copy(update={"sfx_kind": sfx})
            result.append(normalized)
            previous = normalized
        return DirectionPlan(cues=result)

    def validate(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
    ) -> list[str]:
        problems: list[str] = []
        beats = {beat.id: beat for beat in script.all_beats}
        counts = Counter(cue.beat_id for cue in plan.cues)
        if not plan.cues:
            problems.append("direction plan has no cues")
        if plan.cues and all(cue.mascot_pose == MascotPose.NEUTRAL for cue in plan.cues):
            problems.append("direction plan uses only the neutral pose")
        if len(script.beats) >= 2 and not any(
            cue.mascot_pose in self.left_poses for cue in plan.cues
        ):
            problems.append("direction plan never points left")
        if len(script.beats) >= 2 and not any(
            cue.mascot_pose in self.right_poses for cue in plan.cues
        ):
            problems.append("direction plan never points right")
        for beat_id, count in counts.items():
            if count > (3 if beat_id == "hook" else 2):
                problems.append(f"beat '{beat_id}' has more than two cues")
        previous: DirectionCue | None = None
        for cue in plan.cues:
            beat = beats.get(cue.beat_id)
            if beat is None:
                problems.append(f"unknown beat '{cue.beat_id}'")
                continue
            if cue.word_index >= len(beat.text.split()):
                problems.append(f"word index outside beat '{cue.beat_id}'")
            if cue.mascot_anchor != MascotAnchor.CENTER:
                problems.append(f"beat '{cue.beat_id}' moves the mascot anchor")
            if cue.product_focus == Focus.LEFT and cue.mascot_pose not in self.left_poses:
                problems.append(f"left-focused beat '{cue.beat_id}' does not point left")
            if cue.product_focus == Focus.RIGHT and cue.mascot_pose not in self.right_poses:
                problems.append(f"right-focused beat '{cue.beat_id}' does not point right")
            if previous is not None and (
                cue.mascot_pose == previous.mascot_pose
                and cue.product_focus == previous.product_focus
            ):
                problems.append(f"beat '{cue.beat_id}' repeats a visual no-op cue")
            previous = cue
        return list(dict.fromkeys(problems))

    def fallback(self, script: ReferenceScriptPackage) -> DirectionPlan:
        cues: list[DirectionCue] = []
        body_index = 0
        left_name = script.left_item.casefold()
        right_name = script.right_item.casefold()
        for index, beat in enumerate(script.all_beats):
            text = beat.text.casefold()
            if beat.id == "closing":
                pose = MascotPose.THUMBS_UP
                focus = Focus.BOTH
            elif left_name in text and right_name not in text:
                pose = MascotPose.POINT_UP_LEFT
                focus = Focus.LEFT
            elif right_name in text and left_name not in text:
                pose = MascotPose.POINT_UP_RIGHT
                focus = Focus.RIGHT
            elif index == 0:
                pose = MascotPose.PRESENT_BOTH
                focus = Focus.BOTH
            else:
                focus = Focus.LEFT if body_index % 2 == 0 else Focus.RIGHT
                pose = MascotPose.POINT_UP_LEFT if focus == Focus.LEFT else MascotPose.POINT_UP_RIGHT
                body_index += 1
            cues.append(DirectionCue(
                beat_id=beat.id,
                word_index=0,
                mascot_pose=pose,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=focus,
                sfx_kind=SfxKind.POSE_POP,
            ))
        return self.align_with_script(DirectionPlan(cues=cues), script)
