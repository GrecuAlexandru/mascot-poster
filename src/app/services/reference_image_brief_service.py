from __future__ import annotations

from app.domain.models import PairedImageBrief, ProductImageBrief, ResearchPackage, TopicSpec


ATMOSPHERIC_CUE_TERMS = (
    "steam",
    "vapor",
    "mist",
    "fog",
    "heat shimmer",
    "condensation",
    "frost",
    "water droplets",
    "thermal activity",
    "reflective sheen",
)

ABSENCE_TERMS = (
    "absence",
    "absent",
    "missing",
    "no ",
    "lack",
    "without",
    "not visible",
    "does not show",
)


def contains_atmospheric_cue(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in ATMOSPHERIC_CUE_TERMS)


def observable_image_brief(brief: ProductImageBrief) -> ProductImageBrief:
    attributes = [
        attribute
        for attribute in brief.distinguishing_attributes
        if not contains_atmospheric_cue(attribute)
    ]
    if not attributes:
        attributes = [f"recognizable {brief.item}"]
    required = [
        element
        for element in brief.required_elements
        if not contains_atmospheric_cue(element)
    ]
    exact_subject = (
        brief.item
        if contains_atmospheric_cue(brief.exact_subject)
        else brief.exact_subject
    )
    return brief.model_copy(update={
        "exact_subject": exact_subject,
        "distinguishing_attributes": attributes,
        "required_elements": required,
    })


def is_atmospheric_absence_reason(reason: str) -> bool:
    lowered = reason.casefold()
    return (
        any(term in lowered for term in ATMOSPHERIC_CUE_TERMS)
        and any(term in lowered for term in ABSENCE_TERMS)
    )


_IMAGE_BRIEF_SYSTEM_PROMPT = (
    "You are a product-image art director for a Romanian short-form comparison channel. For two "
    "items that a narrator compares side by side, you write a strict PAIRED visual brief that three "
    "downstream systems will obey without argument: a stock-photo image search, an image generator, "
    "and a strict quality validator. Because of that, every attribute you require must be something "
    "a single still photograph can actually prove. Use visual facts, never marketing claims, and "
    "return the brief as structured JSON only."
)

_IMAGE_BRIEF_GUIDE = """

SCHEMA FIELD GUIDE (fill one shared_style, plus a left and a right block)
- shared_style: one sentence describing the SAME camera and lighting for both sides so they read
  as a matched pair: one three-quarter camera angle, matching object scale and crop, neutral studio
  lighting, centered full object, transparent background.
- exact_subject: the precise physical thing to show, in a few concrete words, e.g. "a rectangular
  block of pale yellow butter, partly unwrapped".
- search_query_en: 3-8 plain English words naming the object for a stock-photo search, with no
  style directions, e.g. "butter block unwrapped isolated white background".
- distinguishing_attributes: the visible features that separate this item from the OTHER one. Each
  must be verifiable in a still photo. One to four is plenty; do not pad.
- required_elements: extra props that make the identity unmistakable (for example a truthful
  source-ingredient cue). Leave empty when the object alone is already clear.
- prohibited_elements: always include at least logo, watermark, and unrelated text; then add the
  OTHER item's defining features so the two never blur together.
- confusing_alternatives: items this could be mistaken for; the validator uses them to reject
  lookalikes.
- allow_packaging / allow_text: false by DEFAULT. Set either true only when a generic label or
  container is the ONLY truthful way to establish identity.
- requires_real_reference: true ONLY when faithful real-world appearance is essential (brands,
  named product models, vehicle makes or models, operating systems, apps, websites, recognizable
  interfaces). false for generic physical objects such as food, tools, clothing, materials, or
  containers.
- image_text_language: "none" unless readable text is intrinsic and essential; then "romanian"
  only when that intrinsic text should genuinely be Romanian, otherwise "english".

WHAT A PHOTO CAN AND CANNOT PROVE
Never require temperatures, degrees, durations, tastes, smells, sounds, weights, or other hidden
measurements. Atmospheric cues (steam, condensation, frost, surface sheen) may support an image but
can NEVER be mandatory and can never prove temperature or freshness. Never invent a visual
difference a real photograph could not show. When two items look nearly identical (two white
powders, two clear oils), require a truthful source cue or a concise generic label instead of
leaning on a subtle shade or texture.

WORKED EXAMPLES (illustration only; match the pattern, not the exact items)

Example A - generic food, distinct shapes (Unt vs Margarina):
{
  "shared_style": "one shared three-quarter camera angle, matching object scale and crop, neutral studio lighting, centered full object, transparent background",
  "left": {"item": "Unt", "exact_subject": "a rectangular block of pale yellow butter, partly unwrapped", "search_query_en": "butter block unwrapped isolated white background", "distinguishing_attributes": ["solid rectangular stick shape", "firm cut edges", "pale creamy yellow"], "required_elements": ["a small curl of butter beside the block"], "prohibited_elements": ["logo", "watermark", "unrelated text", "plastic tub"], "confusing_alternatives": ["margarine tub", "cheese"], "allow_packaging": false, "allow_text": false, "requires_real_reference": false, "image_text_language": "none"},
  "right": {"item": "Margarina", "exact_subject": "a round plastic tub of margarine with a smooth scooped surface", "search_query_en": "margarine tub open soft spread isolated white background", "distinguishing_attributes": ["round plastic tub", "soft glossy spreadable surface", "uniform light yellow"], "required_elements": ["a butter knife resting on the tub"], "prohibited_elements": ["logo", "watermark", "unrelated text", "solid stick shape"], "confusing_alternatives": ["butter block", "cream cheese"], "allow_packaging": false, "allow_text": false, "requires_real_reference": false, "image_text_language": "none"}
}

Example B - lookalikes that need a source cue (Unt de arahide vs Unt de migdale):
Both are brown spreads in a jar and look almost identical, so require whole source nuts as proof.
{
  "shared_style": "one shared three-quarter camera angle, matching jar size and crop, neutral studio lighting, centered full object, transparent background",
  "left": {"item": "Unt de arahide", "exact_subject": "an open glass jar of smooth peanut butter", "search_query_en": "peanut butter jar with peanuts isolated white background", "distinguishing_attributes": ["light brown smooth spread", "open glass jar"], "required_elements": ["a small pile of whole shelled peanuts beside the jar"], "prohibited_elements": ["logo", "watermark", "unrelated text", "almonds"], "confusing_alternatives": ["almond butter", "hazelnut spread"], "allow_packaging": false, "allow_text": false, "requires_real_reference": false, "image_text_language": "none"},
  "right": {"item": "Unt de migdale", "exact_subject": "an open glass jar of smooth almond butter", "search_query_en": "almond butter jar with almonds isolated white background", "distinguishing_attributes": ["tan smooth spread", "open glass jar"], "required_elements": ["a small pile of whole almonds beside the jar"], "prohibited_elements": ["logo", "watermark", "unrelated text", "peanuts"], "confusing_alternatives": ["peanut butter", "cashew butter"], "allow_packaging": false, "allow_text": false, "requires_real_reference": false, "image_text_language": "none"}
}

Example C - digital interfaces (Motor de cautare vs Feed video):
Use the real device form factor and a GENERIC interface layout; do not require a brand logo or exact copy.
{
  "shared_style": "two identical smartphones held upright, same size and crop, neutral studio lighting, centered, transparent background",
  "left": {"item": "Motor de cautare", "exact_subject": "a smartphone showing a generic search-engine results page", "search_query_en": "smartphone search results page mockup white background", "distinguishing_attributes": ["a search bar across the top", "a vertical list of plain text link results"], "required_elements": [], "prohibited_elements": ["watermark", "brand logo"], "confusing_alternatives": ["video feed", "map app"], "allow_packaging": false, "allow_text": false, "requires_real_reference": true, "image_text_language": "none"},
  "right": {"item": "Feed video", "exact_subject": "a smartphone showing a generic full-screen vertical video feed", "search_query_en": "smartphone vertical video feed mockup white background", "distinguishing_attributes": ["a full-screen vertical video", "a right-side column of round action icons"], "required_elements": [], "prohibited_elements": ["watermark", "brand logo"], "confusing_alternatives": ["search results", "photo gallery"], "allow_packaging": false, "allow_text": false, "requires_real_reference": true, "image_text_language": "none"}
}

Example D - vehicles, show the complete object with the proving cue (Masina electrica vs Masina pe benzina):
Never substitute an isolated part; show the whole car plus the cue that proves the difference.
{
  "shared_style": "one shared three-quarter front angle, matching car scale and crop, neutral studio lighting, centered full vehicle, transparent background",
  "left": {"item": "Masina electrica", "exact_subject": "a complete modern electric car with a charging cable plugged into its side port", "search_query_en": "electric car charging cable plugged isolated white background", "distinguishing_attributes": ["a charging plug in a side charge port", "no exhaust pipe", "smooth closed front grille"], "required_elements": ["the charging cable connected to the port"], "prohibited_elements": ["watermark", "unrelated text", "fuel nozzle"], "confusing_alternatives": ["gasoline car", "hybrid car"], "allow_packaging": false, "allow_text": false, "requires_real_reference": true, "image_text_language": "none"},
  "right": {"item": "Masina pe benzina", "exact_subject": "a complete conventional car refuelling at a fuel filler with a pump nozzle inserted", "search_query_en": "car refuelling gas pump nozzle isolated white background", "distinguishing_attributes": ["a fuel pump nozzle in the fuel filler", "a visible exhaust pipe", "an open front grille"], "required_elements": ["the fuel nozzle inserted in the filler"], "prohibited_elements": ["watermark", "unrelated text", "charging cable"], "confusing_alternatives": ["electric car", "hybrid car"], "allow_packaging": false, "allow_text": false, "requires_real_reference": true, "image_text_language": "none"}
}
"""


class ReferenceImageBriefService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
    ) -> PairedImageBrief:
        facts = "\n".join(f"- {fact.text}" for fact in research.facts) or "- No additional facts"
        system = _IMAGE_BRIEF_SYSTEM_PROMPT
        user = (
            f"Comparison: {topic.comparison_left} versus {topic.comparison_right}.\n"
            f"Research:\n{facts}\n"
            "Define the exact physical subject for each side and the visible attributes that "
            "distinguish it from the opposing item. Every required attribute must be directly "
            "verifiable in a single still photo. Atmospheric cues such as steam, condensation, or "
            "surface sheen may support the image, but they cannot prove temperature, freshness, or "
            "other hidden properties. Never make atmospheric cues mandatory. Never require temperatures, "
            "degrees, durations, tastes, smells, sounds, weights, or other measurements that a "
            "photograph cannot prove. Never invent or exaggerate visual differences that a real "
            "product photograph cannot reliably show. If an unbranded product alone cannot prove "
            "the comparison category, require an unmistakable truthful source-ingredient cue, such "
            "as whole peanuts beside peanut butter and whole almonds beside almond butter. If no "
            "natural source cue can identify it, require a concise generic identity label and Set "
            "allow_text to true. Set allow_packaging to true when that label is attached to the container. "
            "Never use subtle color or texture differences as the only distinction "
            "between visually similar foods, powders, oils, pills, liquids, or pastes. Allow essential "
            "generic packaging when it is the only truthful way to establish identity. Require physically plausible, natural product "
            "photography with real-world materials, colors, and proportions. Use one shared three-quarter camera angle, "
            "matching object scale and crop, neutral studio lighting, centered full-object framing, "
            "and transparent background. Explicitly prohibit logos, watermarks, unrelated text, "
            "cropped edges, and the other item's defining attributes. Packaging and text should be "
            "false by default, but may be true when essential to identify either a branded or unbranded "
            "lookalike product. For vehicles, appliances, "
            "or complex systems, select a complete, matching context view that visibly proves the "
            "comparison difference; never substitute an isolated control or component unless the topic "
            "itself compares that component. For each side fill search_query_en with a short English "
            "image-search phrase (3-8 plain words naming the physical object, no style directions) "
            "that a stock-photo search engine would match. For an app, website, search engine, or social "
            "platform comparison, define the real device form factor and generic interaction layout. Do not "
            "require a trademarked logo, platform name, exact UI copy, or pixel-perfect interface. Set "
            "requires_real_reference to true only when faithful real-world appearance is essential to the "
            "comparison: brands, named product models, vehicle makes or models, operating systems, apps, "
            "websites, or recognizable interfaces. Set it false for generic physical objects such as "
            "refrigerators, food, tools, clothing, materials, or containers. Set image_text_language to "
            "none unless readable text is intrinsic and essential to the requested subject. Use romanian only "
            "when that intrinsic text should genuinely be Romanian; otherwise use english."
            + _IMAGE_BRIEF_GUIDE
        )
        result = await self.llm.complete_structured(
            system,
            user,
            PairedImageBrief,
            schema_name="paired_image_brief",
            temperature=0.2,
            max_tokens=1800,
        )
        left = result.left.model_copy(update={"item": topic.comparison_left})
        right = result.right.model_copy(update={"item": topic.comparison_right})
        return result.model_copy(update={
            "left": observable_image_brief(left),
            "right": observable_image_brief(right),
        })
