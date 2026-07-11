from __future__ import annotations

from app.domain.models import PairedImageBrief, ResearchPackage, TopicSpec


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
            "distinguish it from the opposing item. Use one shared three-quarter camera angle, "
            "matching object scale and crop, neutral studio lighting, centered full-object framing, "
            "and transparent background. Explicitly prohibit logos, watermarks, unrelated text, "
            "cropped edges, and the other item's defining attributes. Packaging and text should be "
            "false unless they are essential to identify a branded product."
        )
        result = await self.llm.complete_structured(
            system,
            user,
            PairedImageBrief,
            schema_name="paired_image_brief",
            temperature=0.2,
            max_tokens=1800,
        )
        return result.model_copy(update={
            "left": result.left.model_copy(update={"item": topic.comparison_left}),
            "right": result.right.model_copy(update={"item": topic.comparison_right}),
        })
