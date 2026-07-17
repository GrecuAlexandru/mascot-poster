from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.domain.models import ReferenceScriptPackage, TopicSpec


class ProofItem(BaseModel):
    id: str
    text: str


class ProofResult(BaseModel):
    items: list[ProofItem] = Field(default_factory=list)


_PROOFREAD_SYSTEM_PROMPT = (
    "You are a strict Romanian proofreader for a short-form video channel. You receive short pieces "
    "of Romanian text and return each one corrected ONLY for diacritics (ă, â, î, ș, ț), spelling, "
    "and clear grammatical errors. You never change the meaning, the choice of words, the facts, the "
    "numbers, or the names, and you never add or remove content beyond fixing an actual mistake. The "
    "text is read aloud by a text-to-speech engine, so keep it fully speakable: do not introduce "
    "symbols, abbreviations, or digits. Return structured JSON only."
)

_PROOFREAD_INSTRUCTIONS = (
    "Correct each item below. Return the SAME id for each item, with its text fixed for correct "
    "Romanian diacritics, spelling, and obvious grammar only. If an item is already correct, return "
    "it unchanged. Do NOT rephrase, shorten, expand, translate, or restructure; only fix real "
    "mistakes. Keep proper nouns and the mascot name 'Pufăilă' intact. Examples of the kind of fix "
    "expected: 'la tava' -> 'la tavă'; 'grosă' -> 'groasă'; 'branza' -> 'brânză'; 'paine' -> "
    "'pâine'; 'diferenta' -> 'diferența'; 'facut' -> 'făcut'; 'oua' -> 'ouă'. Do not touch fixed "
    "phrases like 'Pe scurt,' at the start of a sentence.\n\nItems:\n"
)


class ReferenceProofreader:
    """Corrects Romanian diacritics and spelling on generated text without changing meaning."""

    def __init__(self, llm: object):
        self.llm = llm

    async def _correct(self, items: dict[str, str]) -> dict[str, str]:
        cleaned = {key: value for key, value in items.items() if value and value.strip()}
        if not cleaned:
            return dict(items)
        listing = "\n".join(f"- [{key}] {value}" for key, value in cleaned.items())
        try:
            result = await self.llm.complete_structured(
                _PROOFREAD_SYSTEM_PROMPT,
                _PROOFREAD_INSTRUCTIONS + listing,
                ProofResult,
                schema_name="reference_proofread",
                temperature=0.0,
                max_tokens=1600,
            )
        except Exception:
            return dict(items)
        corrected = {item.id: item.text for item in result.items}
        output = dict(items)
        for key, original in cleaned.items():
            fixed = corrected.get(key)
            if self._is_safe_correction(original, fixed):
                output[key] = fixed.strip()
        return output

    @staticmethod
    def _is_safe_correction(original: str, fixed: str | None) -> bool:
        # A proofreading fix must stay close to the original: correcting diacritics or a
        # misspelling never changes the word count much. Anything that rewrites the text is
        # rejected so the proofreader can never hallucinate new content or drop facts.
        if not fixed or not fixed.strip():
            return False
        if fixed.strip() == original:
            return False
        original_words = len(original.split())
        fixed_words = len(fixed.split())
        allowed_delta = max(2, round(original_words * 0.34))
        return abs(fixed_words - original_words) <= allowed_delta

    async def correct_script(self, script: ReferenceScriptPackage) -> ReferenceScriptPackage:
        items: dict[str, str] = {f"beat::{beat.id}": beat.text for beat in script.beats}
        items["caption::"] = script.caption
        corrected = await self._correct(items)
        beats = [
            beat.model_copy(update={"text": corrected.get(f"beat::{beat.id}", beat.text)})
            for beat in script.beats
        ]
        original_beat = next(beat for beat in script.beats if beat.id == script.memory_device.beat_id)
        fixed_beat = next(beat for beat in beats if beat.id == script.memory_device.beat_id)
        original_sentences = self._sentences(original_beat.text)
        fixed_sentences = self._sentences(fixed_beat.text)
        try:
            memory_index = original_sentences.index(script.memory_device.line)
            fixed_line = fixed_sentences[memory_index]
            payload = script.model_dump()
            payload["beats"] = [beat.model_dump() for beat in beats]
            payload["caption"] = corrected.get("caption::", script.caption)
            payload["memory_device"]["line"] = fixed_line
            return ReferenceScriptPackage.model_validate(payload)
        except (ValueError, IndexError):
            return script

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [
            " ".join(sentence.split())
            for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
            if sentence.strip()
        ]

    async def correct_topic(self, topic: TopicSpec) -> TopicSpec:
        items = {
            "title": topic.title,
            "left": topic.comparison_left,
            "right": topic.comparison_right,
            "angle": topic.angle,
        }
        corrected = await self._correct(items)
        return topic.model_copy(update={
            "title": corrected.get("title", topic.title),
            "comparison_left": corrected.get("left", topic.comparison_left),
            "comparison_right": corrected.get("right", topic.comparison_right),
            "angle": corrected.get("angle", topic.angle),
        })
