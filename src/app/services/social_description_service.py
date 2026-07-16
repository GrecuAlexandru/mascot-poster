from __future__ import annotations

from app.domain.models import (
    ReferenceScriptPackage,
    ResearchPackage,
    SocialDescription,
    TopicSpec,
)


class SocialDescriptionService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
        script: ReferenceScriptPackage,
        language: str,
        recent_descriptions: list[str],
    ) -> SocialDescription:
        facts = "\n".join(f"- {fact.text}" for fact in research.facts) or "- none"
        narration = "\n".join(f"- {beat.text}" for beat in script.all_beats)
        recent = "\n".join(f"- {item}" for item in recent_descriptions) or "- none"
        repair_note = "none"
        for _attempt in range(2):
            user = self._prompt(
                topic,
                language,
                facts,
                narration,
                recent,
                repair_note,
            )
            try:
                result = await self.llm.complete_structured(
                    "You write grounded social descriptions for Pufăilă's comparison videos.",
                    user,
                    SocialDescription,
                    schema_name="social_description",
                    temperature=0.45,
                    max_tokens=700,
                )
                self._validate_comparison_opening(result, topic)
                return result
            except Exception as error:
                repair_note = f"Previous result failed validation: {type(error).__name__}: {error}"
        return SocialDescription(
            description=script.caption,
            hashtags=script.hashtags,
            fallback_used=True,
        )

    @staticmethod
    def _validate_comparison_opening(
        result: SocialDescription,
        topic: TopicSpec,
    ) -> None:
        expected = f"{topic.comparison_left} vs {topic.comparison_right}".casefold()
        if not result.description.casefold().startswith(expected):
            raise ValueError(f"description must start with {expected}")

    @staticmethod
    def _prompt(
        topic: TopicSpec,
        language: str,
        facts: str,
        narration: str,
        recent: str,
        repair_note: str,
    ) -> str:
        return f"""Write the final social description in {language}.

CHANNEL VOICE
- Sound like a playful expert: friendly, concrete, lightly witty, and concise.
- Build Pufăilă's own voice. Do not copy Nea Caisă or the phrase «nu știam nici eu».
- Do not copy wording from the recent descriptions.

FORMAT
- Start exactly with: {topic.comparison_left} vs {topic.comparison_right}
- Add one relevant emoji near the comparison.
- Use 25-45 words before hashtags, normally two or three short sentences.
- State one concrete contrast supported by the facts and final narration.
- End with an easy personal-experience or preference question. A persona emoji may follow it.
- Return 3-5 hashtag tokens without # or spaces.
- Include pufaila and stiaica; add category or object-specific tags.
- Use correct Romanian diacritics when language is ro.
- Never add an unsupported claim, clickbait, fake urgency, or generic abstract summary.

TOPIC
Title: {topic.title}
Left: {topic.comparison_left}
Right: {topic.comparison_right}

VERIFIED FACTS
{facts}

FINAL VERIFIED NARRATION
{narration}

RECENT DESCRIPTIONS TO AVOID REPEATING
{recent}

REPAIR NOTE
{repair_note}
"""
