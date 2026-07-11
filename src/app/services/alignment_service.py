from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from app.providers.tts.base import TimedPhrase, TimedWord
from app.rendering.ffmpeg import FFmpegRunner

logger = logging.getLogger(__name__)

WORD_PATTERN = re.compile(r"\S+")


class AlignmentService:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg = FFmpegRunner(ffmpeg_bin, ffprobe_bin)

    def align(
        self,
        text: str,
        audio_path: Path,
        timed_words: Optional[list[TimedWord]] = None,
    ) -> list[TimedWord]:
        if timed_words:
            logger.info("Using provider-supplied word timestamps")
            return timed_words

        logger.info("Falling back to proportional timing")
        return self._proportional_timing(text, audio_path)

    def _proportional_timing(
        self,
        text: str,
        audio_path: Path,
    ) -> list[TimedWord]:
        duration = self.ffmpeg.get_duration(audio_path)
        if duration <= 0:
            logger.warning(f"Could not get audio duration for {audio_path}")
            return []

        words = WORD_PATTERN.findall(text)
        if not words:
            return []

        total_chars = sum(len(w) for w in words)
        if total_chars == 0:
            return []

        result: list[TimedWord] = []
        cumulative_chars = 0
        for word in words:
            word_start = (cumulative_chars / total_chars) * duration
            cumulative_chars += len(word)
            word_end = (cumulative_chars / total_chars) * duration
            cumulative_chars += 1
            result.append(TimedWord(
                word=word,
                start=round(word_start, 3),
                end=round(word_end, 3),
            ))

        if result:
            result[-1].end = duration

        return result

    @staticmethod
    def group_into_phrases(
        words: list[TimedWord],
        max_phrase_words: int = 5,
    ) -> list[TimedPhrase]:
        if not words:
            return []

        phrases: list[TimedPhrase] = []
        current: list[TimedWord] = []

        for word in words:
            current.append(word)
            if len(current) >= max_phrase_words:
                phrases.append(TimedPhrase(
                    text=" ".join(w.word for w in current),
                    start=current[0].start,
                    end=current[-1].end,
                ))
                current = []

        if current:
            phrases.append(TimedPhrase(
                text=" ".join(w.word for w in current),
                start=current[0].start,
                end=current[-1].end,
            ))

        return phrases

    @staticmethod
    def find_phrase_timestamps(
        target_text: str,
        words: list[TimedWord],
    ) -> Optional[TimedPhrase]:
        target_lower = target_text.lower().strip()
        word_texts = [w.word.lower().strip(".,!?;:") for w in words]

        target_words = target_lower.split()
        if not target_words:
            return None

        for i in range(len(word_texts) - len(target_words) + 1):
            match = all(
                word_texts[i + j] == target_words[j].strip(".,!?;:")
                for j in range(len(target_words))
            )
            if match:
                return TimedPhrase(
                    text=target_text,
                    start=words[i].start,
                    end=words[i + len(target_words) - 1].end,
                )

        return None
