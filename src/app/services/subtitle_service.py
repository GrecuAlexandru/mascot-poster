from __future__ import annotations

import logging
import re
from typing import Optional

from app.domain.models import SceneSpec, TimedPhrase, TimedWord

logger = logging.getLogger(__name__)

SENTENCE_END = re.compile(r"[.!?;:]")
KEYWORD_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}\b", re.UNICODE),
    re.compile(r"\b\d+([.,]\d+)?\s*(%|km|h|g|kg|ml|L|secs?|mins?)\b", re.IGNORECASE),
]


class SubtitleService:
    def __init__(self, max_phrase_length: int = 42, max_phrase_words: int = 5):
        self.max_phrase_length = max_phrase_length
        self.max_phrase_words = max_phrase_words

    def select_phrases(
        self,
        narration: str,
        words: list[TimedWord],
    ) -> list[TimedPhrase]:
        if not words or not narration:
            return []

        sentences = self._split_sentences(narration)
        result: list[TimedPhrase] = []

        for sentence in sentences:
            phrase = self._find_phrase_in_words(sentence, words)
            if phrase:
                result.append(phrase)

        result.extend(self._extract_keywords(narration, words))
        return self._deduplicate(result)

    def map_scenes_to_timing(
        self,
        scenes: list[SceneSpec],
        duration_seconds: float,
    ) -> list[SceneSpec]:
        return scenes

    def _split_sentences(self, text: str) -> list[str]:
        parts = SENTENCE_END.split(text)
        return [p.strip() for p in parts if p.strip()]

    def _find_phrase_in_words(
        self,
        phrase_text: str,
        words: list[TimedWord],
    ) -> Optional[TimedPhrase]:
        target_words = phrase_text.lower().split()
        word_texts = [w.word.lower().strip(".,!?;:\"'") for w in words]

        if not target_words:
            return None

        for i in range(len(word_texts) - len(target_words) + 1):
            if all(
                word_texts[i + j] == target_words[j].strip(".,!?;:\"'")
                for j in range(len(target_words))
            ):
                matched = words[i : i + len(target_words)]
                text = " ".join(w.word for w in matched)
                if len(text) <= self.max_phrase_length:
                    return TimedPhrase(
                        text=text,
                        start=matched[0].start,
                        end=matched[-1].end,
                    )
        return None

    def _extract_keywords(
        self,
        text: str,
        words: list[TimedWord],
    ) -> list[TimedPhrase]:
        result: list[TimedPhrase] = []
        word_texts = [w.word for w in words]

        for pattern in KEYWORD_PATTERNS:
            for match in pattern.finditer(text):
                keyword = match.group()
                phrase = self._find_phrase_in_words(keyword, words)
                if phrase:
                    result.append(phrase)

        return result

    def _deduplicate(self, phrases: list[TimedPhrase]) -> list[TimedPhrase]:
        seen: set[str] = set()
        result: list[TimedPhrase] = []
        for p in phrases:
            key = p.text.lower()
            if key not in seen:
                seen.add(key)
                result.append(p)
        return sorted(result, key=lambda p: p.start)
