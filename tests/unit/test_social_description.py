from __future__ import annotations

import asyncio

import pytest

from app.domain.enums import MemoryDeviceKind
from app.domain.models import (
    ClosingBeat,
    NarrationBeat,
    MemoryDevice,
    ReferenceScriptPackage,
    ResearchFact,
    ResearchPackage,
    SocialDescription,
    TopicSpec,
)
from app.services.social_description_service import SocialDescriptionService


VALID_DESCRIPTION = (
    "Frigider vs congelator ❄️ Frigiderul păstrează mâncarea rece, iar congelatorul o "
    "îngheață pentru mai mult timp. Tu ce aliment pui mereu în locul greșit? 🐹"
)


def _topic() -> TopicSpec:
    return TopicSpec(
        title="Frigider vs Congelator",
        comparison_left="Frigider",
        comparison_right="Congelator",
    )


def _research() -> ResearchPackage:
    return ResearchPackage(
        topic="Frigider vs Congelator",
        left_item="Frigider",
        right_item="Congelator",
        facts=[
            ResearchFact(
                id="fact_1",
                text="Frigiderul păstrează alimentele reci fără să le înghețe.",
                source_url="https://example.com/fridge",
            ),
            ResearchFact(
                id="fact_2",
                text="Congelatorul îngheață alimentele pentru păstrare mai lungă.",
                source_url="https://example.com/freezer",
            ),
        ],
    )


def _script() -> ReferenceScriptPackage:
    return ReferenceScriptPackage(
        title="Frigider vs Congelator",
        left_item="Frigider",
        right_item="Congelator",
        hook="Avem frigider și avem congelator.",
        beats=[
            NarrationBeat(
                id="left",
                text="Frigiderul păstrează mâncarea rece fără să o înghețe.",
            ),
            NarrationBeat(
                id="right",
                text="Congelatorul îngheață mâncarea pentru mai mult timp.",
            ),
        ],
        closing=ClosingBeat(id="closing", text="Vă pupă Pufăilă!", pause_after_ms=500),
        caption="Frigider sau congelator? Tu ce alegi?",
        hashtags=["#Frigider", "congelator", "#Pufăilă"],
        memory_device=MemoryDevice(
            kind=MemoryDeviceKind.ANALOGY,
            line="Frigiderul păstrează mâncarea rece fără să o înghețe.",
            beat_id="left",
        ),
    )


def test_social_description_validates_length_and_question() -> None:
    result = SocialDescription(description=VALID_DESCRIPTION, hashtags=["bucătărie"])

    assert result.description == VALID_DESCRIPTION

    with pytest.raises(ValueError, match="25-45 words"):
        SocialDescription(description="Frigider vs congelator. Tu ce alegi?", hashtags=["x"])

    with pytest.raises(ValueError, match="question"):
        SocialDescription(
            description=VALID_DESCRIPTION.replace("greșit?", "greșit."),
            hashtags=["x"],
        )


def test_social_description_allows_any_decorative_emoji_after_final_question() -> None:
    description = VALID_DESCRIPTION.removesuffix("🐹") + "🐷"

    result = SocialDescription(description=description, hashtags=["bucatarie"])

    assert result.description.endswith("? 🐷")


def test_social_description_normalizes_and_formats_hashtags() -> None:
    result = SocialDescription(
        description=VALID_DESCRIPTION,
        hashtags=["#Pufăilă", "#ȘtiaiCă", " Bucătărie ", "frigider!", "FRIGIDER", "congelator", "extra"],
    )

    assert result.normalized_hashtags == [
        "pufaila",
        "stiaica",
        "bucatarie",
        "frigider",
        "congelator",
    ]
    assert result.publishable_text == (
        f"{VALID_DESCRIPTION}\n\n"
        "#pufaila #stiaica #bucatarie #frigider #congelator"
    )


def test_social_description_service_uses_final_grounded_inputs_and_channel_voice() -> None:
    class LLM:
        def __init__(self) -> None:
            self.calls = []

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.calls.append((system, user, model_type, kwargs))
            return SocialDescription(
                description=VALID_DESCRIPTION,
                hashtags=["bucatarie", "frigider", "congelator"],
            )

    llm = LLM()
    result = asyncio.run(
        SocialDescriptionService(llm).generate(
            _topic(),
            _research(),
            _script(),
            "ro",
            recent_descriptions=["Cafea vs nes ☕ Tu ce alegi?"],
        )
    )

    prompt = llm.calls[0][1]
    assert result.fallback_used is False
    assert "Frigiderul păstrează mâncarea rece" in prompt
    assert "Congelatorul îngheață alimentele" in prompt
    assert "Cafea vs nes" in prompt
    assert "playful expert" in prompt
    assert "25-45" in prompt
    assert "nu știam nici eu" in prompt
    assert "do not copy" in prompt.lower()
    assert llm.calls[0][2] is SocialDescription
    assert llm.calls[0][3] == {
        "schema_name": "social_description",
        "temperature": 0.45,
        "max_tokens": 700,
    }


def test_social_description_service_repairs_once_then_falls_back() -> None:
    class RepairingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("missing final question")
            return SocialDescription(
                description=VALID_DESCRIPTION,
                hashtags=["bucatarie"],
            )

    repairing = RepairingLLM()
    repaired = asyncio.run(
        SocialDescriptionService(repairing).generate(
            _topic(), _research(), _script(), "ro", []
        )
    )
    assert repairing.calls == 2
    assert repaired.fallback_used is False

    class FailingLLM:
        async def complete_structured(self, system, user, model_type, **kwargs):
            raise RuntimeError("provider unavailable")

    fallback = asyncio.run(
        SocialDescriptionService(FailingLLM()).generate(
            _topic(), _research(), _script(), "ro", []
        )
    )

    assert fallback.fallback_used is True
    assert fallback.description == _script().caption
    assert fallback.normalized_hashtags[:2] == ["pufaila", "stiaica"]
