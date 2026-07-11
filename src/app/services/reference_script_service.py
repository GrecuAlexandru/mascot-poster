from __future__ import annotations

from app.domain.models import ReferenceScriptPackage, ResearchPackage, TopicSpec


class ReferenceScriptService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
        target_duration_seconds: int,
        language: str,
        repair_notes: list[str] | None = None,
    ) -> ReferenceScriptPackage:
        facts = "\n".join(f"- {fact.text}" for fact in research.facts) or "- Fără fapte suplimentare"
        language_name = "română" if language == "ro" else "English"
        word_budget = target_duration_seconds * 2
        system = (
            "You write factual short-form comparison narration as structured JSON. "
            "Return short spoken beats with explicit permitted pauses."
        )
        user = (
            f"Scrie în {language_name}. Topic: {topic.title}. "
            f"Stânga: {topic.comparison_left}. Dreapta: {topic.comparison_right}. "
            f"Țintă: {target_duration_seconds} secunde. "
            "Folosește 6-9 beat-uri, text vorbit natural, fiecare cu un id stabil, "
            "iar pause_after_ms trebuie să fie una dintre 0, 150, 300, 500, 750. "
            f"Textul vorbit total trebuie să aibă cel mult {word_budget} cuvinte. "
            "Nu inventa fapte în afara listei.\nFapte:\n"
            f"{facts}\nReparații cerute:\n{chr(10).join(repair_notes or ['niciuna'])}"
        )
        result = await self.llm.complete_structured(
            system,
            user,
            ReferenceScriptPackage,
            schema_name="reference_script",
            temperature=0.35,
            max_tokens=2800,
        )
        return result.model_copy(update={
            "title": topic.title,
            "left_item": topic.comparison_left,
            "right_item": topic.comparison_right,
        })
