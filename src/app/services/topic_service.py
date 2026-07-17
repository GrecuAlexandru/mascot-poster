from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

from app.domain.models import TopicCandidate, TopicSpec
from app.providers.llm.base import LLMError, LLMProvider
from app.services.topic_selection_service import TopicSelectionService

if TYPE_CHECKING:
    from app.services.topic_history import TopicHistoryService

logger = logging.getLogger(__name__)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

STYLE_GUIDANCE = {
    "en": (
        "- Energetic and conversational\n"
        "- Avoid generic AI phrasing\n"
        "- Keep claims simple\n"
        "- Prefer active voice\n"
        "- Use vocabulary suitable for short-form educational content"
    ),
    "ro": (
        "- Natural conversational Romanian\n"
        "- Avoid literal English translations\n"
        "- Correct diacritics (ă, â, î, ș, ț)\n"
        "- Avoid overly formal wording\n"
        "- Avoid unnatural marketing phrases\n"
        "- Use short spoken sentences"
    ),
}

_TOPIC_SYSTEM_PROMPT = (
    "You are a topic generator for a short-form comparison video channel. "
    "You always respond with valid JSON."
)


class TopicService:
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
        self.selector = TopicSelectionService()

    def create_manual_topic(
        self,
        left: str,
        right: str,
        angle: str = "",
        title: Optional[str] = None,
    ) -> TopicSpec:
        if not left.strip() or not right.strip():
            raise ValueError("Both left and right items are required")
        resolved_title = title or f"{left} vs {right}"
        return TopicSpec(
            title=resolved_title,
            comparison_left=left,
            comparison_right=right,
            angle=angle,
            status="IDEA",
        )

    async def generate_topics(
        self,
        niche: str = "",
        language: str = "en",
        count: int = 10,
        previous_topics: Optional[list[str]] = None,
        blacklist: Optional[list[str]] = None,
    ) -> list[TopicCandidate]:
        if not self.llm:
            raise LLMError("No LLM provider configured for topic generation")
        if count < 1 or count > 30:
            raise ValueError("count must be between 1 and 30")

        template = self._load_prompt("topic_generation.md")
        user_prompt = template.format(
            count=count,
            niche=niche or "open — any domain",
            language=language,
            previous_topics=self._format_list(previous_topics or []),
            blacklist=self._format_list(blacklist or []),
        )

        data = await self.llm.complete_json(
            system_prompt=_TOPIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.8,
        )

        topics_data = data.get("topics", [])
        candidates: list[TopicCandidate] = []
        for td in topics_data:
            try:
                candidates.append(TopicCandidate(**td))
            except Exception as e:
                logger.warning(f"Skipping invalid topic candidate: {e}")

        logger.info(f"Generated {len(candidates)} topic candidates")
        return candidates

    async def generate_unique_topics(
        self,
        history: "TopicHistoryService",
        niche: str = "",
        language: str = "en",
        count: int = 10,
        blacklist: Optional[list[str]] = None,
    ) -> list[TopicCandidate]:
        existing_titles = history.get_topic_titles()

        candidates = await self.generate_topics(
            niche=niche,
            language=language,
            count=min(30, count * 2),
            previous_topics=existing_titles,
            blacklist=blacklist,
        )

        unique = self.selector.select(
            candidates,
            existing_pairs=history.get_normalized_pairs(),
            blacklist=blacklist,
            limit=count,
        )

        logger.info(
            f"Filtered to {len(unique)} unique topics "
            f"(from {len(candidates)} candidates, history={history.count})"
        )
        return unique

    def deduplicate(
        self,
        candidates: list[TopicCandidate],
        existing: Optional[list[TopicSpec]] = None,
    ) -> list[TopicCandidate]:
        existing_norms = set()
        for t in existing or []:
            norm = self._normalize(f"{t.comparison_left} {t.comparison_right}")
            existing_norms.add(norm)

        seen: set[str] = set()
        result: list[TopicCandidate] = []
        for c in candidates:
            norm = self._normalize(f"{c.left} {c.right}")
            if norm in existing_norms:
                logger.info(f"Skipping duplicate topic: {c.title}")
                continue
            if norm in seen:
                continue
            seen.add(norm)
            result.append(c)
        return result

    def filter_by_risk(
        self,
        candidates: list[TopicCandidate],
        allow_high_risk: bool = False,
    ) -> list[TopicCandidate]:
        if allow_high_risk:
            return list(candidates)
        return [c for c in candidates if c.risk_level != "high"]

    def filter_blacklist(
        self,
        candidates: list[TopicCandidate],
        blacklist: list[str],
    ) -> list[TopicCandidate]:
        if not blacklist:
            return list(candidates)
        norms = {self._normalize(b) for b in blacklist}
        return [
            c
            for c in candidates
            if self._normalize(c.left) not in norms
            and self._normalize(c.right) not in norms
        ]

    @staticmethod
    def _normalize(text: str) -> str:
        return _NORMALIZE_RE.sub("", text.lower()).strip()

    @staticmethod
    def _format_list(items: list[str]) -> str:
        if not items:
            return "(none)"
        return "\n".join(f"- {item}" for item in items[:20])

    def _load_prompt(self, name: str) -> str:
        from pathlib import Path

        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        path = prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def get_style_guidance(self, language: str) -> str:
        return STYLE_GUIDANCE.get(language, STYLE_GUIDANCE["en"])
