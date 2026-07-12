from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.job_cost_ledger import (
    JobCostLedger,
    cost_scope,
    record_cost_event,
)
from app.providers.llm.openai_provider import LLMProvider
from app.providers.tts.base import TTSResult, TimedWord, TTSSettings
from app.domain.models import ClosingBeat, NarrationBeat, ReferenceScriptPackage
from app.services.beat_tts_service import BeatTTSService


def test_cost_ledger_groups_actual_and_estimated_events(tmp_path: Path) -> None:
    ledger = JobCostLedger("job-1")
    with cost_scope(ledger, "script"):
        record_cost_event(
            provider="openrouter",
            model="deepseek/test",
            operation="completion",
            input_units=100,
            output_units=20,
            unit_type="tokens",
            amount_usd=0.0123456,
            amount_kind="actual",
            pricing_source="provider_usage",
            request_key="script-1",
        )
    with cost_scope(ledger, "tts"):
        record_cost_event(
            provider="elevenlabs",
            model="eleven_multilingual_v2",
            operation="synthesize",
            input_units=80,
            unit_type="characters",
            amount_usd=0.024,
            amount_kind="estimated",
            pricing_source="provider_estimate",
            request_key="beat-1",
        )

    report = ledger.report()
    path = tmp_path / "cost_report.json"
    ledger.save(path)

    assert report.actual_total_usd == pytest.approx(0.012346)
    assert report.estimated_total_usd == pytest.approx(0.024)
    assert report.projected_total_usd == pytest.approx(0.036346)
    assert report.by_provider["openrouter"] == pytest.approx(0.012346)
    assert report.by_stage["tts"] == pytest.approx(0.024)
    assert json.loads(path.read_text(encoding="utf-8"))["job_id"] == "job-1"


def test_cost_ledger_deduplicates_stable_events_and_counts_failures() -> None:
    ledger = JobCostLedger("job-1")
    for _ in range(2):
        with cost_scope(ledger, "images"):
            record_cost_event(
                provider="openrouter",
                operation="image_generation",
                amount_usd=0.0,
                amount_kind="estimated",
                pricing_source="request_failed",
                status="failed",
                error="rate limited",
                request_key="attempt-1",
            )

    assert len(ledger.events) == 1
    assert ledger.report().failed_calls == 1


def test_cost_ledger_counts_changed_result_for_same_request_as_retry() -> None:
    ledger = JobCostLedger("job-1")
    with cost_scope(ledger, "script"):
        record_cost_event(
            provider="openrouter",
            operation="chat_completion",
            status="failed",
            error="rate limited",
            request_key="same-request",
        )
        record_cost_event(
            provider="openrouter",
            operation="chat_completion",
            amount_usd=0.01,
            amount_kind="actual",
            pricing_source="provider_usage",
            request_key="same-request",
        )

    assert [event.attempt for event in ledger.events] == [1, 2]
    assert ledger.report().retry_calls == 1


def test_cost_ledger_loads_existing_events_without_duplication(tmp_path: Path) -> None:
    path = tmp_path / "cost_report.json"
    first = JobCostLedger("job-1")
    with cost_scope(first, "search"):
        record_cost_event(
            provider="tavily",
            operation="search",
            input_units=1,
            unit_type="queries",
            amount_usd=0.008,
            request_key="query-1",
        )
    first.save(path)

    resumed = JobCostLedger.load(path, "job-1")
    with cost_scope(resumed, "search"):
        record_cost_event(
            provider="tavily",
            operation="search",
            input_units=1,
            unit_type="queries",
            amount_usd=0.008,
            request_key="query-1",
        )

    assert len(resumed.events) == 1


def test_cost_scopes_are_isolated_between_async_jobs() -> None:
    async def record(job_id: str) -> JobCostLedger:
        ledger = JobCostLedger(job_id)
        with cost_scope(ledger, "tts"):
            await asyncio.sleep(0)
            record_cost_event(
                provider="elevenlabs",
                operation="synthesize",
                amount_usd=0.01,
                request_key="beat-1",
            )
        return ledger

    async def run_both():
        return await asyncio.gather(record("a"), record("b"))

    first, second = asyncio.run(run_both())

    assert first.events[0].job_id == "a"
    assert second.events[0].job_id == "b"


def test_openrouter_usage_prefers_provider_reported_actual_cost() -> None:
    ledger = JobCostLedger("job-1")
    provider = LLMProvider(api_key="test", model="deepseek/test")
    with cost_scope(ledger, "script"):
        provider._record_usage({
            "model": "deepseek/test",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "cost": 0.0042,
            },
        }, "chat_completion")

    event = ledger.events[0]
    assert event.amount_kind == "actual"
    assert event.amount_usd == pytest.approx(0.0042)
    assert event.input_units == 100
    assert event.output_units == 25


def test_beat_tts_records_one_estimated_event_per_beat(tmp_path: Path) -> None:
    class Provider:
        async def synthesize(self, text, voice_id, language, output_path, settings, **kwargs):
            output_path.write_bytes(b"audio")
            return TTSResult(
                path=output_path,
                duration_seconds=1.0,
                provider="elevenlabs",
                model=settings.model_id,
                character_count=len(text),
                estimated_cost_usd=0.01,
                timed_words=[TimedWord(word=text, start=0.0, end=1.0)],
            )

    class Audio:
        def concatenate_with_silence(self, segments, output_path):
            output_path.write_bytes(b"joined")

        def get_duration(self, output_path):
            return 2.5

    script = ReferenceScriptPackage(
        title="A vs B",
        left_item="A",
        right_item="B",
        hook="Hook",
        beats=[NarrationBeat(id="b0", text="First beat.", pause_after_ms=300)],
        closing=ClosingBeat(
            id="closing",
            text="Therefore choose the option that fits your needs best.",
            pause_after_ms=500,
        ),
        caption="A or B?",
    )
    ledger = JobCostLedger("job-1")
    with cost_scope(ledger, "tts"):
        asyncio.run(BeatTTSService(Provider(), Audio()).synthesize(
            script,
            "voice",
            "en",
            tmp_path,
            TTSSettings(speed=0.8),
        ))

    events = [event for event in ledger.events if event.operation == "synthesize"]
    assert len(events) == 2
    assert all(event.amount_kind == "estimated" for event in events)
    assert sum(event.amount_usd for event in events) == pytest.approx(0.02)
