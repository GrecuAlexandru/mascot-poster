from __future__ import annotations

from app.domain.enums import SfxKind
from app.domain.models import (
    AbsoluteDirectionCue,
    CaptionCue,
    CompiledTimeline,
    DirectionPlan,
    SoundEffectCue,
    TimedTranscript,
)


class TimelineCompiler:
    def __init__(
        self,
        max_caption_words: int = 4,
        max_caption_characters: int = 26,
        reset_gap_seconds: float = 0.3,
        sfx_debounce_seconds: float = 0.6,
    ):
        self.max_caption_words = max_caption_words
        self.max_caption_characters = max_caption_characters
        self.reset_gap_seconds = reset_gap_seconds
        self.sfx_debounce_seconds = sfx_debounce_seconds

    def compile(
        self,
        direction: DirectionPlan,
        transcript: TimedTranscript,
    ) -> CompiledTimeline:
        result = self.compile_direction(direction, transcript)
        result.captions = self.compile_captions(transcript)
        return result

    def compile_captions(self, transcript: TimedTranscript) -> list[CaptionCue]:
        result: list[CaptionCue] = []
        current_words: list[str] = []
        previous = None
        words = transcript.words
        for index, word in enumerate(words):
            if self._starts_new_caption(current_words, previous, word):
                current_words = []
            current_words.append(word.word)
            next_start = words[index + 1].start if index + 1 < len(words) else transcript.duration_seconds
            end = max(word.end, next_start)
            result.append(CaptionCue(
                words=list(current_words),
                active_word_index=len(current_words) - 1,
                start=word.start,
                end=end,
            ))
            previous = word
        return result

    def compile_direction(
        self,
        direction: DirectionPlan,
        transcript: TimedTranscript,
    ) -> CompiledTimeline:
        words_by_beat = self._words_by_beat(transcript)
        absolute_cues: list[AbsoluteDirectionCue] = []
        for cue in direction.cues:
            beat_words = words_by_beat.get(cue.beat_id)
            if beat_words is None:
                raise ValueError(f"Unknown beat_id '{cue.beat_id}'")
            if cue.word_index >= len(beat_words):
                raise ValueError(
                    f"word_index {cue.word_index} outside beat '{cue.beat_id}'"
                )
            absolute_cues.append(AbsoluteDirectionCue(
                start=beat_words[cue.word_index].start,
                mascot_pose=cue.mascot_pose,
                mascot_anchor=cue.mascot_anchor,
                product_focus=cue.product_focus,
                sfx_kind=cue.sfx_kind,
            ))
        absolute_cues.sort(key=lambda cue: cue.start)
        sound_cues = self._sound_cues(absolute_cues)
        return CompiledTimeline(
            direction_cues=absolute_cues,
            sound_cues=sound_cues,
        )

    def _starts_new_caption(self, current_words: list[str], previous, word) -> bool:
        if not current_words or previous is None:
            return False
        if previous.word.rstrip().endswith((".", "!", "?", ";", ":")):
            return True
        if word.start - previous.end > self.reset_gap_seconds:
            return True
        if len(current_words) >= self.max_caption_words:
            return True
        return len(" ".join([*current_words, word.word])) > self.max_caption_characters

    @staticmethod
    def _words_by_beat(transcript: TimedTranscript) -> dict[str, list]:
        result: dict[str, list] = {}
        for beat in transcript.beats:
            result[beat.id] = [
                word
                for word in transcript.words
                if word.start >= beat.start - 0.001 and word.end <= beat.end + 0.001
            ]
        return result

    def _sound_cues(
        self,
        direction_cues: list[AbsoluteDirectionCue],
    ) -> list[SoundEffectCue]:
        result: list[SoundEffectCue] = []
        last_start = -self.sfx_debounce_seconds
        for cue in direction_cues:
            if cue.sfx_kind == SfxKind.NONE:
                continue
            if cue.start - last_start < self.sfx_debounce_seconds:
                continue
            result.append(SoundEffectCue(start=cue.start, kind=cue.sfx_kind))
            last_start = cue.start
        return result
