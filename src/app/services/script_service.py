from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.domain.models import ScriptPackage, TopicSpec
from app.providers.llm.base import LLMError, LLMProvider
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)

_SCRIPT_SYSTEM_PROMPT = (
    "You are a script writer for short-form comparison videos. "
    "You always respond with valid JSON. No markdown fences."
)


class ScriptService:
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
        self.topic_svc = TopicService(llm_provider)

    async def generate_script(
        self,
        topic: TopicSpec,
        niche: str = "food facts",
        language: str = "en",
        target_duration_seconds: int = 60,
        research_facts: Optional[list[str]] = None,
        forbidden_claims: Optional[list[str]] = None,
        previous_hooks: Optional[list[str]] = None,
        available_poses: Optional[list[str]] = None,
        canvas_width: int = 1080,
        canvas_height: int = 1920,
        max_repair_attempts: int = 2,
    ) -> ScriptPackage:
        if not self.llm:
            raise LLMError("No LLM provider configured for script generation")

        target_word_count = max(130, int(target_duration_seconds * 2.7))

        template = self._load_prompt("script_generation.md")
        user_prompt = template.format(
            niche=niche,
            language=language,
            target_duration_seconds=target_duration_seconds,
            target_word_count=target_word_count,
            title=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            angle=topic.angle,
            research_facts=self._format_facts(research_facts or []),
            forbidden_claims=self._format_list(forbidden_claims or []),
            previous_hooks=self._format_list(previous_hooks or []),
            available_poses=self._format_list(available_poses or _default_poses()),
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            style_guidance=self.topic_svc.get_style_guidance(language),
        )

        data = await self.llm.complete_json(
            system_prompt=_SCRIPT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=4096,
        )

        for attempt in range(max_repair_attempts + 1):
            try:
                return ScriptPackage(**data)
            except ValidationError as e:
                if attempt >= max_repair_attempts:
                    logger.error(f"Script validation failed after {max_repair_attempts + 1} attempts")
                    raise LLMError(f"Script validation failed: {e}")
                logger.warning(
                    f"Script validation failed (attempt {attempt + 1}), "
                    f"requesting repair..."
                )
                repair_prompt = (
                    f"The following JSON failed validation with this error:\n{e}\n\n"
                    f"Fix the JSON to match the required schema. "
                    f"Return ONLY valid JSON.\n\n"
                    f"Original JSON:\n{json.dumps(data)}"
                )
                raw = await self.llm.complete(
                    system_prompt=_SCRIPT_SYSTEM_PROMPT,
                    user_prompt=repair_prompt,
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                data = json.loads(raw)

        raise LLMError("unreachable")

    def validate_script(self, script: ScriptPackage) -> list[str]:
        problems: list[str] = []

        if script.word_count < 80:
            problems.append(f"Word count {script.word_count} is below minimum 80")
        if script.word_count > 250:
            problems.append(f"Word count {script.word_count} exceeds maximum 250")

        if not script.hook.strip():
            problems.append("Hook is empty")

        if not script.caption.strip():
            problems.append("Caption is empty")

        for i, scene in enumerate(script.scenes):
            if scene.duration_hint_seconds < 0.5:
                problems.append(f"Scene {i} duration too short")
            if scene.duration_hint_seconds > 8.0:
                problems.append(f"Scene {i} duration too long")

        if script.scenes:
            estimated = sum(s.duration_hint_seconds for s in script.scenes)
            if abs(estimated - script.estimated_duration_seconds) > 15:
                problems.append(
                    f"Sum of scene durations ({estimated:.1f}s) "
                    f"differs from estimated ({script.estimated_duration_seconds:.1f}s)"
                )

        for claim in script.claims:
            if claim.risk_level == "high" and claim.confidence < 0.9:
                problems.append(
                    f"High-risk claim '{claim.id}' has low confidence: {claim.confidence}"
                )

        return problems

    @staticmethod
    def _format_facts(facts: list[str]) -> str:
        if not facts:
            return "(no research facts provided — use general knowledge only)"
        return "\n".join(f"- {f}" for f in facts)

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


def _default_poses() -> list[str]:
    return [
        "neutral", "point_left", "point_right", "point_up", "point_down",
        "arms_open", "thinking", "surprised", "warning", "thumbs_up",
    ]
