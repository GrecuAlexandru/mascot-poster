from __future__ import annotations

from app.domain.enums import MascotPose
from app.domain.models import DirectionPlan, ReferenceScriptPackage
from app.services.reference_direction_validator import ReferenceDirectionValidator


_DIRECTION_SYSTEM_PROMPT = (
    "You are the visual director for a reference-style short-form comparison video. The two compared "
    "products sit at the TOP of a vertical frame and the mascot Pufaila stands at the BOTTOM, so it "
    "points UP and to the side to look toward whichever item the narration is talking about. When "
    "the narration covers both items or a general idea, the mascot drops the point and uses an open, "
    "non-pointing pose instead. For chosen words inside each spoken beat you return expressive cues: "
    "the mascot pose, which product is in focus, the mascot anchor, and a small sound accent. Return "
    "only these structured cues as JSON, nothing else."
)

_DIRECTION_GUIDE = """
CORE RULES
- Always use mascot_anchor "center" so the mascot's calibrated feet never move.
- product_focus is one of left, right, both, neutral, from the VIEWER's perspective.
- THE GOLDEN RULE: the mascot points at the item the words are about, and ONLY at that item.
  A beat about the left item uses pose "point_up_left" with product_focus "left"; a beat about
  the right item uses "point_up_right" with product_focus "right" (the products sit ABOVE the
  mascot, so it points up and looks toward the item it discusses).
- A beat about BOTH items at once, or about the general idea (a verdict, a summary, a fun fact
  that belongs to neither item), must NOT point. Use a non-pointing pose: present_both or
  compare_left_right when it frames the pair, explaining / thinking / surprised / idea / warning
  for a general thought.
- A pose STAYS ON SCREEN until your next cue. Never leave a point "hanging": when the previous
  beat pointed at one item and the new beat talks about both items or the general idea, place a
  cue on that beat's FIRST word with a non-pointing pose to release the point. A mascot that
  keeps pointing at an item it is no longer talking about looks broken.
- Beat ids tell you the side: an id starting with "left_" describes the left item and an id
  starting with "right_" describes the right item, even when the beat text does not repeat the
  item's name (a continuation like "Gust puternic, picant" after a left_ beat is still LEFT).
  Keep pointing at that same side for such continuation beats; never flip to the other side just
  because a new beat starts.
- word_index is 0-based into the beat's word list shown at the end. Place a cue on the FIRST
  word that introduces the pose or focus change (usually the product's name).
- ONE cue per beat is the norm. Use TWO only when the pose genuinely changes mid-beat; the hook
  may have up to three. Never more.
- Never return an all-neutral plan. Keep poses varied and expressive; do not repeat the same
  pose+focus back to back (that is a visual no-op).
- The app finalizes the sound accents automatically (a "pose_pop" on a pose change, a "focus_tick"
  on a focus-only change), so just set sfx_kind to "pose_pop" by default; do not obsess over it.

WHEN A BEAT DISCUSSES BOTH PRODUCTS
Return ONE cue on the beat's first word with a non-pointing pose that frames the pair:
present_both, or compare_left_right for a verdict-style contrast, with product_focus "both".
Example, for the beat "Untul e din lapte, margarina din uleiuri.": one cue on "Untul" with
present_both + both. Incorrect: point_up_left on "Untul" and point_up_right on "margarina", a
single one-sided pointing cue, or keeping the previous beat's pointing pose.

POSE MENU (pick the pose that fits the moment)
- point_up_left / point_up_right: REQUIRED whenever a beat names or describes ONLY the left /
  right product. This is the workhorse pair.
- present_both / compare_left_right: REQUIRED for a beat about both items together (the verdict,
  a side-by-side sentence, the memory line that contrasts the two).
- intro_hands_up: opening energy on the hook question.
- idea: a clever tip, trick, or realization.
- thinking / magnifying_glass / reading_note: setting up a question or inspecting a detail before
  a reveal.
- surprised: a genuine "stai, chiar asa?" reveal.
- warning: a caution, limitation, or "ai grija" moment.
- explaining: a general thought that belongs to neither product; also the standard release pose
  after pointing.
- thumbs_up / celebrate: a positive verdict or upbeat close.
- shrug: a "depinde / nu conteaza" moment.
- neutral: a resting default; never use it for the whole plan.
- point_up / point_down / two_fingers_up / arms_crossed / phone_in_hand / outro_wave: occasional
  accents when they genuinely fit.

WORKED EXAMPLE (LEFT item "Unt", RIGHT item "Margarina")
Given beats:
  left_origine: 0:Untul 1:se 2:face 3:din 4:smantana 5:batuta 6:pur 7:din 8:lapte
  left_gust: 0:Are 1:gust 2:plin 3:si 4:se 5:rumeneste 6:frumos
  right_origine: 0:Margarina 1:se 2:face 3:din 4:uleiuri 5:vegetale 6:rafinate
  compara: 0:Untul 1:e 2:din 3:lapte 4:margarina 5:din 6:uleiuri
  verdict: 0:Pe 1:scurt 2:unul 3:e 4:din 5:lapte 6:celalalt 7:din 8:uleiuri
A correct plan:
{
  "cues": [
    {"beat_id": "left_origine", "word_index": 0, "mascot_pose": "point_up_left", "mascot_anchor": "center", "product_focus": "left", "sfx_kind": "pose_pop"},
    {"beat_id": "right_origine", "word_index": 0, "mascot_pose": "point_up_right", "mascot_anchor": "center", "product_focus": "right", "sfx_kind": "pose_pop"},
    {"beat_id": "compara", "word_index": 0, "mascot_pose": "present_both", "mascot_anchor": "center", "product_focus": "both", "sfx_kind": "pose_pop"},
    {"beat_id": "verdict", "word_index": 0, "mascot_pose": "compare_left_right", "mascot_anchor": "center", "product_focus": "both", "sfx_kind": "pose_pop"}
  ]
}
Note: left_gust has NO cue, so the mascot keeps pointing left while the narration keeps
describing the left item. compara talks about both products, so ONE non-pointing cue frames the
pair instead of pointing. verdict is the general conclusion: compare_left_right releases the
point; the mascot never keeps pointing at one item during a verdict or a summary.
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
