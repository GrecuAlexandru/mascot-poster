from __future__ import annotations

import logging
from typing import Optional

from app.domain.models import ResearchFact, ResearchPackage, SourceReference, TopicSpec
from app.providers.llm.base import LLMError, LLMProvider
from app.providers.search.base import SearchProvider, SearchResponse

logger = logging.getLogger(__name__)

_SOURCE_TYPE_TRUST = {
    "official": 0.95,
    "government": 0.90,
    "scientific": 0.85,
    "reference": 0.80,
    "journalism": 0.75,
    "retail": 0.60,
    "blog": 0.30,
    "social": 0.10,
    "unknown": 0.50,
}

_BANNED_DOMAINS = {
    "tiktok.com", "instagram.com", "facebook.com",
    "pinterest.com", "reddit.com",
}

_RESEARCH_SYSTEM_PROMPT = (
    "You are a research synthesizer for short-form comparison videos. "
    "You always respond with valid JSON. No markdown fences."
)


class ResearchService:
    def __init__(
        self,
        search_provider: Optional[SearchProvider] = None,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.search = search_provider
        self.llm = llm_provider

    def build_queries(self, topic: TopicSpec) -> list[str]:
        left = topic.comparison_left
        right = topic.comparison_right
        angle = topic.angle

        queries = [
            f"{left} vs {right} {angle}".strip(),
            f"what is {left}",
            f"what is {right}",
            f"difference between {left} and {right}",
            f"{left} ingredients composition",
            f"{right} ingredients composition",
        ]

        if angle:
            queries.append(f"{left} {right} {angle} explained")

        return queries[:6]

    async def search_topic(
        self,
        topic: TopicSpec,
        max_results_per_query: int = 5,
    ) -> list[SearchResponse]:
        if not self.search:
            raise LLMError("No search provider configured")

        queries = self.build_queries(topic)
        responses: list[SearchResponse] = []

        for q in queries:
            try:
                resp = await self.search.search(q, max_results_per_query)
                responses.append(resp)
            except Exception as e:
                logger.warning(f"Search failed for '{q}': {e}")

        logger.info(
            f"Research search: {len(queries)} queries, "
            f"{sum(len(r.results) for r in responses)} total results"
        )
        return responses

    def score_source(self, url: str, title: str, snippet: str) -> tuple[float, str]:
        source_type = self._classify_source(url, title, snippet)
        base_trust = _SOURCE_TYPE_TRUST.get(source_type, 0.5)

        domain = self._extract_domain(url).lower()
        if domain in _BANNED_DOMAINS:
            base_trust *= 0.2
            source_type = "social"

        return base_trust, source_type

    def _classify_source(self, url: str, title: str, snippet: str) -> str:
        lower_url = url.lower()
        lower_title = title.lower()
        combined = f"{lower_url} {lower_title}"

        if any(w in combined for w in (".gov", "government", "fda.gov", "usda.gov", "ema.europa")):
            return "government"
        if any(w in combined for w in ("sciencedirect", "pubmed", "doi.org", "nature.com", "springer", "wiley", "academic", "journal", "research")):
            return "scientific"
        if any(w in combined for w in ("wikipedia.org", "britannica", "dictionary")):
            return "reference"
        if any(w in combined for w in ("reuters", "bbc", "nytimes", "guardian", "bloomberg", "apnews")):
            return "journalism"
        if any(w in combined for w in ("amazon", "ebay", "shop", "store", "product")):
            return "retail"
        if any(w in combined for w in ("blog", "medium", "substack")):
            return "blog"
        if any(w in combined for w in ("tiktok", "instagram", "facebook", "twitter", "youtube", "reddit")):
            return "social"
        if any(w in combined for w in ("manufacturer", "official", "brand")):
            return "official"
        return "unknown"

    def _extract_domain(self, url: str) -> str:
        clean = url.replace("https://", "").replace("http://", "").replace("www.", "")
        return clean.split("/")[0]

    def deduplicate_sources(
        self,
        responses: list[SearchResponse],
    ) -> list[SourceReference]:
        seen_urls: set[str] = set()
        sources: list[SourceReference] = []

        for resp in responses:
            for i, result in enumerate(resp.results):
                url = result.url
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                trust, source_type = self.score_source(url, result.title, result.snippet)
                sources.append(SourceReference(
                    id=f"src_{len(sources)}",
                    url=url,
                    title=result.title,
                    publisher=self._extract_domain(url),
                    trust_score=round(trust, 2),
                    source_type=source_type,
                ))

        sources.sort(key=lambda s: s.trust_score, reverse=True)
        return sources

    async def synthesize(
        self,
        topic: TopicSpec,
        search_responses: list[SearchResponse],
        sources: list[SourceReference],
    ) -> ResearchPackage:
        if not self.llm:
            return self._fallback_synthesize(topic, sources)

        template = self._load_prompt("research_synthesis.md")
        search_text = self._format_search_results(search_responses, sources)

        user_prompt = template.format(
            title=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            angle=topic.angle or "general comparison",
            language="en",
            search_results=search_text,
        )

        data = await self.llm.complete_json(
            system_prompt=_RESEARCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )

        facts: list[ResearchFact] = []
        for fd in data.get("facts", []):
            try:
                facts.append(ResearchFact(**fd))
            except Exception as e:
                logger.warning(f"Skipping invalid research fact: {e}")

        pkg_sources: list[SourceReference] = []
        for sd in data.get("sources", []):
            try:
                pkg_sources.append(SourceReference(**sd))
            except Exception as e:
                logger.warning(f"Skipping invalid source: {e}")

        if not pkg_sources:
            pkg_sources = sources

        result = ResearchPackage(
            topic=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            facts=facts,
            sources=pkg_sources,
            unresolved_questions=data.get("unresolved_questions", []),
            safety_notes=data.get("safety_notes", []),
        )

        logger.info(
            f"Research package: {len(result.facts)} facts, "
            f"{len(result.sources)} sources, "
            f"{len(result.unresolved_questions)} unresolved"
        )
        return result

    def _fallback_synthesize(
        self,
        topic: TopicSpec,
        sources: list[SourceReference],
    ) -> ResearchPackage:
        facts: list[ResearchFact] = []
        for s in sources[:5]:
            facts.append(ResearchFact(
                text=f"Source mentions: {s.title}",
                source_ids=[s.id],
                confidence=s.trust_score,
                applies_to="general",
            ))
        return ResearchPackage(
            topic=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            facts=facts,
            sources=sources,
            unresolved_questions=[],
            safety_notes=[],
        )

    @staticmethod
    def _format_search_results(
        responses: list[SearchResponse],
        sources: list[SourceReference],
    ) -> str:
        lines: list[str] = []
        for s in sources[:15]:
            lines.append(
                f"- [{s.id}] {s.title} ({s.publisher}, trust={s.trust_score})\n"
                f"  URL: {s.url}\n"
                f"  Type: {s.source_type}"
            )
        if not lines:
            return "(no search results available)"
        return "\n".join(lines)

    def _load_prompt(self, name: str) -> str:
        from pathlib import Path

        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        path = prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def has_blocking_issues(pkg: ResearchPackage) -> Optional[str]:
        if pkg.safety_notes:
            return f"Safety notes: {'; '.join(pkg.safety_notes)}"
        if pkg.unresolved_questions and len(pkg.unresolved_questions) >= 3:
            return (
                f"Too many unresolved questions: "
                f"{len(pkg.unresolved_questions)}"
            )
        return None
