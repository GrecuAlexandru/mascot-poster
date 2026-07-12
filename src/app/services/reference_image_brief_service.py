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


class ReferenceImageBriefService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
    ) -> PairedImageBrief:
        facts = "\n".join(f"- {fact.text}" for fact in research.facts) or "- No additional facts"
        system = (
            "You are a product-image art director. Return a strict paired visual brief "
            "for two unmistakable comparison objects. Use visual facts, not marketing claims."
        )
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
