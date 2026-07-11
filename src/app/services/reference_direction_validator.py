from __future__ import annotations

from collections import Counter

from app.domain.enums import Focus, MascotAnchor, MascotPose, SfxKind
from app.domain.models import DirectionCue, DirectionPlan, ReferenceScriptPackage


class ReferenceDirectionValidator:
    left_poses = {MascotPose.POINT_LEFT, MascotPose.POINT_UP_LEFT}
    right_poses = {MascotPose.POINT_RIGHT, MascotPose.POINT_UP_RIGHT}

    def normalize(self, plan: DirectionPlan) -> DirectionPlan:
        result: list[DirectionCue] = []
        previous: DirectionCue | None = None
        for cue in plan.cues:
            normalized = cue.model_copy(update={"mascot_anchor": MascotAnchor.CENTER})
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
            if count > 2:
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
                pose = MascotPose.POINT_LEFT
                focus = Focus.LEFT
            elif right_name in text and left_name not in text:
                pose = MascotPose.POINT_RIGHT
                focus = Focus.RIGHT
            elif index == 0:
                pose = MascotPose.PRESENT_BOTH
                focus = Focus.BOTH
            else:
                focus = Focus.LEFT if body_index % 2 == 0 else Focus.RIGHT
                pose = MascotPose.POINT_LEFT if focus == Focus.LEFT else MascotPose.POINT_RIGHT
                body_index += 1
            cues.append(DirectionCue(
                beat_id=beat.id,
                word_index=0,
                mascot_pose=pose,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=focus,
                sfx_kind=SfxKind.POSE_POP,
            ))
        return DirectionPlan(cues=cues)
