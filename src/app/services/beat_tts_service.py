from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.domain.models import (
    ReferenceScriptPackage,
    TimedBeat,
    TimedTranscript,
    TimedWord,
)
from app.providers.tts.base import TTSSettings
from app.services.job_cost_ledger import record_cost_event


class BeatTTSService:
    def __init__(self, provider: object, audio_service: object):
        self.provider = provider
        self.audio_service = audio_service

    async def synthesize(
        self,
        script: ReferenceScriptPackage,
        voice_id: str,
        language: str,
        output_dir: Path,
        settings: Optional[TTSSettings] = None,
    ) -> tuple[Path, TimedTranscript]:
        output_dir.mkdir(parents=True, exist_ok=True)
        settings = settings or TTSSettings()
        segments: list[tuple[Path, int]] = []
        timed_words: list[TimedWord] = []
        timed_beats: list[TimedBeat] = []
        offset = 0.0
        previous_text = ""

        for index, beat in enumerate(script.all_beats):
            segment_path = output_dir / f"beat_{index:02d}.mp3"
            request_key = f"{beat.id}:{beat.text}"
            beat_settings = self._settings_for_beat(settings, beat.id)
            try:
                result = await self.provider.synthesize(
                    text=beat.text,
                    voice_id=voice_id,
                    language=language,
                    output_path=segment_path,
                    settings=beat_settings,
                    previous_text=previous_text or None,
                    seed=42,
                )
            except Exception as error:
                record_cost_event(
                    provider=getattr(self.provider, "name", "tts"),
                    model=beat_settings.model_id,
                    operation="synthesize",
                    input_units=len(beat.text),
                    unit_type="characters",
                    amount_usd=0.0,
                    pricing_source="request_failed",
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                    request_key=request_key,
                )
                raise
            record_cost_event(
                provider=result.provider,
                model=result.model,
                operation="synthesize",
                input_units=result.character_count,
                unit_type="characters",
                amount_usd=0.0 if result.cached else result.estimated_cost_usd,
                amount_kind="estimated",
                pricing_source="cache_hit" if result.cached else "provider_estimate",
                cached=result.cached,
                request_key=request_key,
            )
            words = result.timed_words or self._proportional_words(
                beat.text,
                result.duration_seconds,
            )
            for word in words:
                timed_words.append(TimedWord(
                    word=word.word,
                    start=round(offset + word.start, 3),
                    end=round(offset + word.end, 3),
                ))

            beat_end = offset + result.duration_seconds
            pause_end = beat_end + beat.pause_after_ms / 1000.0
            timed_beats.append(TimedBeat(
                id=beat.id,
                start=round(offset, 3),
                end=round(beat_end, 3),
                pause_end=round(pause_end, 3),
            ))
            segments.append((segment_path, beat.pause_after_ms))
            offset = pause_end
            previous_text = beat.text

        output_path = output_dir / "narration.wav"
        self.audio_service.concatenate_with_silence(segments, output_path)
        decoded_duration = (
            self.audio_service.get_duration(output_path)
            if hasattr(self.audio_service, "get_duration")
            else offset
        )
        final_word_end = timed_words[-1].end if timed_words else 0.0
        narration_end = max(offset, decoded_duration, final_word_end)
        transcript = TimedTranscript(
            words=timed_words,
            beats=timed_beats,
            duration_seconds=round(narration_end, 3),
        )
        return output_path, transcript

    @staticmethod
    def _settings_for_beat(settings: TTSSettings, beat_id: str) -> TTSSettings:
        if beat_id == "closing":
            return settings.model_copy(update={"speed": 0.88})
        return settings

    @staticmethod
    def _proportional_words(text: str, duration: float) -> list[TimedWord]:
        tokens = text.split()
        if not tokens:
            return []
        weights = [max(len(token.strip(".,!?;:")), 1) for token in tokens]
        total = sum(weights)
        result: list[TimedWord] = []
        elapsed = 0.0
        for token, weight in zip(tokens, weights):
            start = elapsed
            elapsed += duration * weight / total
            result.append(TimedWord(word=token, start=start, end=elapsed))
        result[-1].end = duration
        return result
