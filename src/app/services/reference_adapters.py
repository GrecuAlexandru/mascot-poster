from __future__ import annotations

import asyncio
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.domain.models import (
    ReferenceScriptPackage,
    ResearchFact,
    ResearchPackage,
    TopicCandidate,
    TopicSpec,
    VerificationResult,
)
from app.services.research_service import ResearchService


class ReferenceResearchFact(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    source_ids: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    applies_to: Literal["left", "right", "both", "general"] = "general"


class ReferenceResearchSummary(BaseModel):
    facts: list[ReferenceResearchFact] = Field(default_factory=list, max_length=6)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=3)
    safety_notes: list[str] = Field(default_factory=list, max_length=3)


class ReferenceTopicGenerator:
    def __init__(self, llm: object, history: Optional[object] = None):
        self.llm = llm
        self.history = history

    async def generate(self, request) -> TopicSpec:
        if request.topic_override:
            return self._parse_override(request.topic_override)
        previous_topics = []
        if self.history is not None:
            previous_topics = self.history.get_topic_titles()
        candidate = await self.llm.complete_structured(
            "You generate one fact-focused comparison topic as structured JSON.",
            "Generate one broad, visual, Romanian-friendly comparison that is not in this history: "
            + "; ".join(previous_topics[:30]),
            TopicCandidate,
            schema_name="reference_topic",
            temperature=0.65,
            max_tokens=900,
        )
        topic = TopicSpec(
            title=candidate.title,
            comparison_left=candidate.left,
            comparison_right=candidate.right,
            angle=candidate.angle,
        )
        if self.history is not None:
            self.history.add_from_topic(topic)
        return topic

    @staticmethod
    def _parse_override(value: str) -> TopicSpec:
        parts = re.split(r"\s+(?:vs\.?|versus)\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError("Topic override must use the form 'Left vs Right'")
        return TopicSpec(
            title=f"{parts[0].strip()} vs {parts[1].strip()}",
            comparison_left=parts[0].strip(),
            comparison_right=parts[1].strip(),
        )


class ReferenceResearcher:
    def __init__(self, search_provider: object, llm: object):
        self.search_provider = search_provider
        self.llm = llm
        self._scoring = ResearchService(search_provider=search_provider)

    async def generate(self, topic: TopicSpec) -> ResearchPackage:
        queries = self._scoring.build_queries(topic)[:4]
        responses = await asyncio.gather(
            *(self.search_provider.search(query, 5) for query in queries)
        )
        sources = self._scoring.deduplicate_sources(list(responses))
        facts = "\n".join(
            f"- {source.id}: {source.title}; {source.url}" for source in sources[:12]
        ) or "- No verified source results"
        result = await self.llm.complete_structured(
            "You synthesize compact comparison research using only supplied source results.",
            f"Topic: {topic.title}\nLeft: {topic.comparison_left}\nRight: {topic.comparison_right}\n"
            f"Sources:\n{facts}\n\n"
            "Return at most 6 facts. Each fact must be under 280 characters and cite one to three "
            "listed source IDs. Do not repeat, summarize, or return source objects; the application "
            "already stores those separately. Keep unresolved questions and safety notes to at most 3 each.",
            ReferenceResearchSummary,
            schema_name="reference_research",
            temperature=0.1,
            max_tokens=1200,
        )
        available_ids = {source.id for source in sources}
        research_facts = [
            fact.model_copy(update={
                "source_ids": [source_id for source_id in fact.source_ids if source_id in available_ids],
            })
            for fact in result.facts
        ]
        return ResearchPackage(
            topic=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            facts=[
                ResearchFact(**fact.model_dump())
                for fact in research_facts
                if fact.source_ids
            ],
            sources=sources[:12],
            unresolved_questions=result.unresolved_questions,
            safety_notes=result.safety_notes,
        )


class ReferenceVerifier:
    def __init__(self, service: object):
        self.service = service

    async def verify(
        self,
        script: ReferenceScriptPackage,
        research: ResearchPackage,
        topic: TopicSpec,
    ) -> VerificationResult:
        return await self.service.verify(
            narration=script.narration_text,
            claims=script.claims,
            research=research,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            angle=topic.angle,
        )
