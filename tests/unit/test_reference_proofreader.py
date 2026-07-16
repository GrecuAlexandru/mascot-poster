from __future__ import annotations

import asyncio

from app.domain.models import (
    ClosingBeat,
    GenerationRequest,
    NarrationBeat,
    ReferenceScriptPackage,
    TopicCandidate,
    TopicSpec,
)
from app.services.reference_adapters import ReferenceTopicGenerator
from app.services.reference_proofreader import (
    ProofItem,
    ProofResult,
    ReferenceProofreader,
)
from app.services.reference_script_service import ReferenceScriptService


_FIX = {
    "Are o coaja grosă.": "Are o coajă groasă.",
    "Pe scurt, una e grosă.": "Pe scurt, una e groasă.",
    "Paine sau tava? Diferenta?": "Pâine sau tavă? Diferența?",
    "Paine la cuptor": "Pâine la cuptor",
    "Paine la tava": "Pâine la tavă",
    "Paine la cuptor vs Paine la tava": "Pâine la cuptor vs Pâine la tavă",
    "Doua feluri de paine.": "Două feluri de pâine.",
    "Avem Paine la cuptor si avem Paine la tava. Dar care e diferenta?":
        "Avem Pâine la cuptor și avem Pâine la tavă. Dar care e diferența?",
}


class _CorrectingLLM:
    async def complete_structured(self, system, user, model, **kwargs):
        items = []
        for line in user.splitlines():
            line = line.strip()
            if line.startswith("- ["):
                key = line[3:line.index("]")]
                text = line[line.index("]") + 2:]
                items.append(ProofItem(id=key, text=_FIX.get(text, text)))
        return ProofResult(items=items)


class _RewritingLLM:
    async def complete_structured(self, system, user, model, **kwargs):
        items = []
        for line in user.splitlines():
            line = line.strip()
            if line.startswith("- ["):
                key = line[line.index("[") + 1:line.index("]")]
                items.append(ProofItem(
                    id=key,
                    text="cu totul altceva mult mai lung adaugand fapte noi si multe cuvinte",
                ))
        return ProofResult(items=items)


class _BoomLLM:
    async def complete_structured(self, *args, **kwargs):
        raise RuntimeError("boom")


def _sample_script() -> ReferenceScriptPackage:
    return ReferenceScriptPackage(
        title="t",
        left_item="Pâine la cuptor",
        right_item="Pâine la tavă",
        hook="h",
        beats=[
            NarrationBeat(id="hook", text="Are o coaja grosă.", pause_after_ms=500, claim_ids=["c1"]),
            NarrationBeat(id="verdict", text="Pe scurt, una e grosă.", pause_after_ms=750),
        ],
        closing=ClosingBeat(text="Vă pupă Pufăilă!", pause_after_ms=500),
        caption="Paine sau tava? Diferenta?",
        hashtags=["x"],
        claims=[],
    )


def test_proofreader_corrects_beats_and_caption_preserving_structure() -> None:
    fixed = asyncio.run(ReferenceProofreader(_CorrectingLLM()).correct_script(_sample_script()))

    assert fixed.beats[0].text == "Are o coajă groasă."
    assert fixed.beats[0].pause_after_ms == 500
    assert fixed.beats[0].claim_ids == ["c1"]
    assert fixed.beats[1].text == "Pe scurt, una e groasă."
    assert fixed.caption == "Pâine sau tavă? Diferența?"
    assert fixed.closing.text == "Vă pupă Pufăilă!"


def test_proofreader_corrects_topic_labels() -> None:
    topic = TopicSpec(
        title="Paine la cuptor vs Paine la tava",
        comparison_left="Paine la cuptor",
        comparison_right="Paine la tava",
        angle="Doua feluri de paine.",
    )

    fixed = asyncio.run(ReferenceProofreader(_CorrectingLLM()).correct_topic(topic))

    assert fixed.comparison_left == "Pâine la cuptor"
    assert fixed.comparison_right == "Pâine la tavă"
    assert fixed.title == "Pâine la cuptor vs Pâine la tavă"
    assert fixed.angle == "Două feluri de pâine."


def test_proofreader_rejects_a_rewrite_and_keeps_original() -> None:
    fixed = asyncio.run(ReferenceProofreader(_RewritingLLM()).correct_script(_sample_script()))
    assert fixed.beats[0].text == "Are o coaja grosă."
    assert fixed.caption == "Paine sau tava? Diferenta?"


def test_proofreader_falls_back_to_original_on_llm_error() -> None:
    fixed = asyncio.run(ReferenceProofreader(_BoomLLM()).correct_script(_sample_script()))
    assert fixed.caption == "Paine sau tava? Diferenta?"


def test_script_service_runs_proofreader_for_romanian() -> None:
    class ScriptLLM:
        async def complete_structured(self, system, user, model, **kwargs):
            return ReferenceScriptPackage(
                title="Pâine la cuptor vs Pâine la tavă",
                left_item="Paine la cuptor",
                right_item="Paine la tava",
                hook="hook",
                beats=[NarrationBeat(id="b0", text="Are o coaja grosă.")],
                closing=ClosingBeat(
                    id="closing",
                    text="Alege ce-ti place. Vă pupă Pufăilă!",
                    pause_after_ms=500,
                ),
                caption="Paine sau tava? Diferenta?",
            )

    service = ReferenceScriptService(ScriptLLM(), ReferenceProofreader(_CorrectingLLM()))
    topic = TopicSpec(title="t", comparison_left="Pâine la cuptor", comparison_right="Pâine la tavă")
    from app.domain.models import ResearchPackage

    result = asyncio.run(service.generate(
        topic,
        ResearchPackage(topic="t", left_item="Pâine la cuptor", right_item="Pâine la tavă"),
        target_duration_seconds=25,
        language="ro",
    ))

    assert result.caption == "Pâine sau tavă? Diferența?"
    assert any("coajă groasă" in beat.text for beat in result.beats)


def test_topic_generator_proofreads_romanian_labels() -> None:
    class TopicLLM:
        async def complete_structured(self, system, user, model, **kwargs):
            return TopicCandidate(
                title="Paine la cuptor vs Paine la tava",
                left="Paine la cuptor",
                right="Paine la tava",
                angle="Doua feluri de paine.",
            )

    generator = ReferenceTopicGenerator(
        TopicLLM(), None, ReferenceProofreader(_CorrectingLLM())
    )
    topic = asyncio.run(generator.generate(GenerationRequest(language="ro")))

    assert topic.comparison_right == "Pâine la tavă"
    assert topic.comparison_left == "Pâine la cuptor"
