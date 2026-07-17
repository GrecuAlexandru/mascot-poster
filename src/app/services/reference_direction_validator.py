from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.domain.enums import Focus, MascotAnchor, MascotPose, SfxKind
from app.domain.models import DirectionCue, DirectionPlan, ReferenceScriptPackage


class ReferenceDirectionValidator:
    left_poses = {MascotPose.POINT_LEFT, MascotPose.POINT_UP_LEFT}
    right_poses = {MascotPose.POINT_RIGHT, MascotPose.POINT_UP_RIGHT}
    directional_poses = {
        MascotPose.POINT_LEFT,
        MascotPose.POINT_RIGHT,
        MascotPose.POINT_UP_LEFT,
        MascotPose.POINT_UP_RIGHT,
    }
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
        left_words = self._tokens(script.left_item)
        right_words = self._tokens(script.right_item)
        beat_side = {
            beat.id: self._beat_side(beat.id, beat.text, left_words, right_words)
            for beat in script.all_beats
        }
        cues: list[DirectionCue] = []
        for cue in plan.cues:
            side = beat_side.get(cue.beat_id, Focus.NEUTRAL)
            if side == Focus.BOTH:
                cues.append(cue)
                continue
            if side == Focus.NEUTRAL:
                # This beat is about the general idea (a verdict, a summary, the closing). A cue
                # that points at or focuses one side here would highlight an item the narration is
                # not talking about, so drop it. Genuine both/neutral cues stay.
                if (
                    cue.product_focus in (Focus.LEFT, Focus.RIGHT)
                    or cue.mascot_pose in self.directional_poses
                ):
                    continue
                cues.append(cue)
                continue
            wrong_poses = self.right_poses if side == Focus.LEFT else self.left_poses
            update: dict = {}
            if cue.product_focus in (Focus.LEFT, Focus.RIGHT) and cue.product_focus != side:
                update["product_focus"] = side
            if cue.mascot_pose in wrong_poses:
                update["mascot_pose"] = self.mirror_poses[cue.mascot_pose]
            cues.append(cue.model_copy(update=update) if update else cue)
        framed = self._enforce_both_frame(DirectionPlan(cues=cues), script, beat_side)
        hooked = self._enforce_hook_cues(framed, script)
        return self._release_stuck_pointing(hooked, script, beat_side)

    @classmethod
    def _beat_side(
        cls,
        beat_id: str,
        text: str,
        left_words: list[str],
        right_words: list[str],
    ) -> Focus:
        words = cls._tokens(text)
        left_pos = cls._find_item(words, left_words, right_words)
        right_pos = cls._find_item(words, right_words, left_words)
        if left_pos is not None and right_pos is not None:
            return Focus.BOTH
        if left_pos is not None:
            return Focus.LEFT
        if right_pos is not None:
            return Focus.RIGHT
        # Continuation beats often describe an item without naming it; the script names those
        # beats with a left_/right_ id prefix so the mascot keeps pointing at the right side.
        lowered = beat_id.casefold()
        if lowered == "left" or lowered.startswith("left_"):
            return Focus.LEFT
        if lowered == "right" or lowered.startswith("right_"):
            return Focus.RIGHT
        return Focus.NEUTRAL

    def _enforce_both_frame(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
        beat_side: dict[str, Focus],
    ) -> DirectionPlan:
        replacements: dict[str, list[DirectionCue]] = {}
        for beat in script.beats:
            if beat.id == "hook" or beat_side.get(beat.id) != Focus.BOTH:
                continue
            # A beat that talks about both items must not point at either one: keep the plan's
            # non-pointing cues (widened to a both focus) or frame the pair with a single cue.
            kept = [
                cue.model_copy(update={"product_focus": Focus.BOTH})
                if cue.product_focus in (Focus.LEFT, Focus.RIGHT)
                else cue
                for cue in plan.cues
                if cue.beat_id == beat.id and cue.mascot_pose not in self.directional_poses
            ]
            if not kept:
                pose = (
                    MascotPose.COMPARE_LEFT_RIGHT
                    if beat.id.casefold().startswith("verdict")
                    else MascotPose.PRESENT_BOTH
                )
                kept = [DirectionCue(
                    beat_id=beat.id,
                    word_index=0,
                    mascot_pose=pose,
                    mascot_anchor=MascotAnchor.CENTER,
                    product_focus=Focus.BOTH,
                )]
            replacements[beat.id] = kept
        result: list[DirectionCue] = []
        known_ids = {beat.id for beat in script.all_beats}
        for beat in script.all_beats:
            if beat.id in replacements:
                result.extend(replacements[beat.id])
            else:
                result.extend(cue for cue in plan.cues if cue.beat_id == beat.id)
        result.extend(cue for cue in plan.cues if cue.beat_id not in known_ids)
        return DirectionPlan(cues=result)

    def _release_stuck_pointing(
        self,
        plan: DirectionPlan,
        script: ReferenceScriptPackage,
        beat_side: dict[str, Focus],
    ) -> DirectionPlan:
        # A pose stays on screen until the next cue, so a general beat with no cue of its own
        # would keep the mascot pointing at an item it is no longer talking about.
        cues_by_beat: dict[str, list[DirectionCue]] = {}
        for cue in plan.cues:
            cues_by_beat.setdefault(cue.beat_id, []).append(cue)
        result: list[DirectionCue] = []
        active_pose: MascotPose | None = None
        for beat in script.all_beats:
            beat_cues = cues_by_beat.pop(beat.id, [])
            if (
                not beat_cues
                and beat_side.get(beat.id) == Focus.NEUTRAL
                and active_pose in self.directional_poses
            ):
                if beat.id == "closing":
                    pose, focus = MascotPose.THUMBS_UP, Focus.BOTH
                elif beat.id.casefold().startswith("verdict"):
                    pose, focus = MascotPose.COMPARE_LEFT_RIGHT, Focus.BOTH
                else:
                    pose, focus = MascotPose.EXPLAINING, Focus.NEUTRAL
                beat_cues = [DirectionCue(
                    beat_id=beat.id,
                    word_index=0,
                    mascot_pose=pose,
                    mascot_anchor=MascotAnchor.CENTER,
                    product_focus=focus,
                )]
            result.extend(beat_cues)
            if beat_cues:
                active_pose = beat_cues[-1].mascot_pose
        for orphan_cues in cues_by_beat.values():
            result.extend(orphan_cues)
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
            if (
                previous is not None
                and normalized.mascot_pose == previous.mascot_pose
                and normalized.product_focus == previous.product_focus
            ):
                # Nothing changes on screen; keeping the cue would only add a spurious sound.
                continue
            if previous is None or normalized.mascot_pose != previous.mascot_pose:
                sfx = SfxKind.POSE_POP
            else:
                sfx = SfxKind.FOCUS_TICK
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
        left_words = self._tokens(script.left_item)
        right_words = self._tokens(script.right_item)
        beat_side = {
            beat.id: self._beat_side(beat.id, beat.text, left_words, right_words)
            for beat in script.all_beats
        }
        if not plan.cues:
            problems.append("direction plan has no cues")
        if plan.cues and all(cue.mascot_pose == MascotPose.NEUTRAL for cue in plan.cues):
            problems.append("direction plan uses only the neutral pose")
        sides = set(beat_side.values())
        if (Focus.LEFT in sides or Focus.BOTH in sides) and not any(
            cue.mascot_pose in self.left_poses for cue in plan.cues
        ):
            problems.append("direction plan never points left")
        if (Focus.RIGHT in sides or Focus.BOTH in sides) and not any(
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
        left_words = self._tokens(script.left_item)
        right_words = self._tokens(script.right_item)
        for index, beat in enumerate(script.all_beats):
            side = self._beat_side(beat.id, beat.text, left_words, right_words)
            if beat.id == "closing":
                pose = MascotPose.THUMBS_UP
                focus = Focus.BOTH
            elif side == Focus.LEFT:
                pose = MascotPose.POINT_UP_LEFT
                focus = Focus.LEFT
            elif side == Focus.RIGHT:
                pose = MascotPose.POINT_UP_RIGHT
                focus = Focus.RIGHT
            elif side == Focus.BOTH or index == 0:
                pose = MascotPose.PRESENT_BOTH
                focus = Focus.BOTH
            else:
                # A general beat frames the idea, never a leftover point at one item.
                pose = MascotPose.EXPLAINING
                focus = Focus.NEUTRAL
            cues.append(DirectionCue(
                beat_id=beat.id,
                word_index=0,
                mascot_pose=pose,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=focus,
                sfx_kind=SfxKind.POSE_POP,
            ))
        return self.normalize(self.align_with_script(DirectionPlan(cues=cues), script))
