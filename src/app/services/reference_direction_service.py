from __future__ import annotations

from app.domain.enums import MascotPose
from app.domain.models import DirectionPlan, ReferenceScriptPackage
from app.services.reference_direction_validator import ReferenceDirectionValidator


_DIRECTION_SYSTEM_PROMPT = (
    "You are the visual director for a reference-style short-form comparison video. The two compared "
    "products sit at the TOP of a vertical frame and the mascot Pufaila stands at the BOTTOM, so it "
    "points UP and to the side to look toward whichever item the narration is talking about. For "
    "chosen words inside each spoken beat you return expressive cues: the mascot pose, which product "
    "is in focus, the mascot anchor, and a small sound accent. Return only these structured cues as "
    "JSON, nothing else."
)

_DIRECTION_GUIDE = """
CORE RULES
- Always use mascot_anchor "center" so the mascot's calibrated feet never move.
- product_focus is one of left, right, both, neutral, from the VIEWER's perspective.
- Because the products are ABOVE the mascot, a beat about the left item uses pose
  "point_up_left" with product_focus "left", and a beat about the right item uses
  "point_up_right" with product_focus "right". The mascot looks up toward the item it names.
- word_index is 0-based into the beat's word list shown at the end. Place a cue on the FIRST
  word that introduces the pose or focus change (usually the product's name).
- Never return more than TWO cues for a normal beat (the hook may have up to three). Use ONE cue
  for a one-sided beat and exactly TWO for a beat that discusses both products.
- Never return an all-neutral plan. Across the whole video you must point left at least once and
  right at least once. Keep poses varied and expressive; do not repeat the same pose+focus back
  to back (that is a visual no-op).
- The app finalizes the sound accents automatically (a "pose_pop" on a pose change, a "focus_tick"
  on a focus-only change), so just set sfx_kind to "pose_pop" by default; do not obsess over it.

WHEN A BEAT CONTINUES THE SAME PRODUCT (names neither product)
Many beats keep describing the product from the previous beat without naming it (e.g. after
"Brânza de burduf se maturează în coajă", the next beat "Gust puternic, picant" is still about the
LEFT cheese). For such a beat, KEEP the same product_focus and pointing side as the previous beat,
or return no cue for it at all. NEVER flip to the other side just because a new beat starts. Point
right only when the beat actually talks about the right-side product, and left only when it talks
about the left-side product.

WHEN A BEAT DISCUSSES BOTH PRODUCTS
Return exactly two cues: one on the first word naming the LEFT product with point_up_left + left,
then one on the first word naming the RIGHT product with point_up_right + right. Example, for the
beat "Untul e din lapte, margarina din uleiuri.": a cue on "Untul" (point_up_left, left) and a cue
on "margarina" (point_up_right, right). Incorrect: a single left cue for the whole beat, or
repeating point_up_left on a beat that also names the right product.

POSE MENU (pick the pose that fits the moment)
- point_up_left / point_up_right: REQUIRED whenever a beat names or describes the left / right
  product. This is the workhorse pair.
- present_both / compare_left_right: a beat that frames both items together without singling one
  out (good for a verdict that names neither product directly).
- intro_hands_up: opening energy on the hook question.
- idea: a clever tip, trick, or realization.
- thinking / magnifying_glass / reading_note: setting up a question or inspecting a detail before
  a reveal.
- surprised: a genuine "stai, chiar asa?" reveal.
- warning: a caution, limitation, or "ai grija" moment.
- explaining: a neutral explanation that singles out neither product.
- thumbs_up / celebrate: a positive verdict or upbeat close.
- shrug: a "depinde / nu conteaza" moment.
- neutral: a resting default; never use it for the whole plan.
- point_up / point_down / two_fingers_up / arms_crossed / phone_in_hand / outro_wave: occasional
  accents when they genuinely fit.

WORKED EXAMPLE (LEFT item "Unt", RIGHT item "Margarina")
Given beats:
  left_origine: 0:Untul 1:se 2:face 3:din 4:smantana 5:batuta 6:pur 7:din 8:lapte
  right_origine: 0:Margarina 1:se 2:face 3:din 4:uleiuri 5:vegetale 6:rafinate
  compara: 0:Untul 1:e 2:din 3:lapte 4:margarina 5:din 6:uleiuri
  verdict: 0:Pe 1:scurt 2:unul 3:e 4:din 5:lapte 6:celalalt 7:din 8:uleiuri
A correct plan:
{
  "cues": [
    {"beat_id": "left_origine", "word_index": 0, "mascot_pose": "point_up_left", "mascot_anchor": "center", "product_focus": "left", "sfx_kind": "pose_pop"},
    {"beat_id": "right_origine", "word_index": 0, "mascot_pose": "point_up_right", "mascot_anchor": "center", "product_focus": "right", "sfx_kind": "pose_pop"},
    {"beat_id": "compara", "word_index": 0, "mascot_pose": "point_up_left", "mascot_anchor": "center", "product_focus": "left", "sfx_kind": "pose_pop"},
    {"beat_id": "compara", "word_index": 4, "mascot_pose": "point_up_right", "mascot_anchor": "center", "product_focus": "right", "sfx_kind": "focus_tick"},
    {"beat_id": "verdict", "word_index": 0, "mascot_pose": "compare_left_right", "mascot_anchor": "center", "product_focus": "both", "sfx_kind": "pose_pop"}
  ]
}
Note: left_origine and right_origine each get ONE cue (single-sided); compara names both products
so it gets TWO cues at the two product names; verdict names neither product directly, so it frames
both with compare_left_right + both.
"""


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
        system = _DIRECTION_SYSTEM_PROMPT
        user = (
            f"Language: {language}. Available poses: {', '.join(pose.value for pose in MascotPose)}. "
            f"On screen, the LEFT side shows '{script.left_item}' and the RIGHT side shows "
            f"'{script.right_item}'. Directions are from the viewer's perspective: a beat about the "
            "left-side item uses product_focus left, a beat about the right-side item uses "
            "product_focus right."
            + _DIRECTION_GUIDE
            + "\nBeat words (word_index is 0-based into each list):\n"
            + chr(10).join(beat_lines)
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
