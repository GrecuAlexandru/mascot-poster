from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.automation.database import AutomationDatabase
from app.automation.job_service import JobService
from app.automation.models import JobState, RegenerationKind
from app.automation.worker import GenerationWorker


class FakeGenerator:
    def __init__(self, output_base: Path, error: Exception | None = None):
        self.output_base = output_base
        self.error = error
        self.requests = []

    async def generate(self, request, progress_callback=None, job_id=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        job_dir = self.output_base / str(job_id)
        pipeline_dir = job_dir / "_pipeline"
        pipeline_dir.mkdir(parents=True)
        video_path = job_dir / "video.mp4"
        video_path.write_bytes(b"generated-video")
        (pipeline_dir / "topic.json").write_text(
            json.dumps({"title": "Cafea vs ceai"}), encoding="utf-8"
        )
        (pipeline_dir / "script_verification.json").write_text(
            json.dumps(
                {
                    "script": {
                        "title": "Cafea vs ceai",
                        "caption": "Tu ce alegi?",
                        "hashtags": ["#cafea", "#ceai"],
                    }
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            render_result=SimpleNamespace(video_path=video_path)
        )


@pytest.fixture
def job_service(tmp_path: Path) -> JobService:
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    return JobService(database)


def test_worker_runs_real_generation_contract_and_records_artifacts(
    tmp_path: Path, job_service: JobService
):
    target = datetime.now(timezone.utc) + timedelta(hours=2)
    queued = job_service.create_job(
        target_at=target,
        topic_override="Cafea vs ceai",
        target_duration_seconds=30,
        voice_id="voice-1",
    )
    generator = FakeGenerator(tmp_path / "jobs")
    worker = GenerationWorker(job_service, generator, worker_id="worker-1")

    result = asyncio.run(worker.run_once())

    assert result is not None
    assert result.id == queued.id
    assert result.state == JobState.WAITING_FOR_APPROVAL
    assert result.topic == "Cafea vs ceai"
    assert result.caption == "Tu ce alegi?\n\n#cafea #ceai"
    assert result.video_path and result.video_path.is_file()
    assert len(result.video_sha256 or "") == 64
    assert generator.requests[0].topic_override == "Cafea vs ceai"
    assert generator.requests[0].target_duration_seconds == 30
    assert generator.requests[0].voice_id == "voice-1"


def test_worker_marks_generation_failure_without_leaking_exception(
    tmp_path: Path, job_service: JobService
):
    queued = job_service.create_job(
        target_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    generator = FakeGenerator(tmp_path / "jobs", RuntimeError("provider unavailable"))
    worker = GenerationWorker(job_service, generator, worker_id="worker-1")

    result = asyncio.run(worker.run_once())

    assert result is not None
    assert result.id == queued.id
    assert result.state == JobState.FAILED
    assert result.error_message == "RuntimeError: provider unavailable"


def test_idle_worker_returns_none(tmp_path: Path, job_service: JobService):
    worker = GenerationWorker(
        job_service,
        FakeGenerator(tmp_path / "jobs"),
        worker_id="worker-1",
    )

    assert asyncio.run(worker.run_once()) is None


def test_regeneration_kind_invalidates_only_required_checkpoints(
    tmp_path: Path, job_service: JobService
):
    job = job_service.create_job(
        target_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    pipeline = tmp_path / "jobs" / job.id / "_pipeline"
    pipeline.mkdir(parents=True)
    stages = [
        "topic",
        "research_assets",
        "script_verification",
        "direction_tts",
        "compiled",
        "render",
        "quality",
    ]
    for stage in stages:
        (pipeline / f"{stage}.json").write_text("{}", encoding="utf-8")
    (pipeline / "state.json").write_text(
        json.dumps({"completed": stages, "failed_stage": None, "error": None}),
        encoding="utf-8",
    )
    job_service.claim_next("worker")
    video = tmp_path / "first.mp4"
    video.write_bytes(b"first")
    ready = job_service.complete_generation(job.id, video, "caption", "topic")
    job_service.request_regeneration(ready.id, RegenerationKind.SCRIPT)
    generator = FakeGenerator(tmp_path / "jobs")
    worker = GenerationWorker(job_service, generator, worker_id="worker-1")

    asyncio.run(worker.run_once())

    assert (pipeline / "topic.json").exists()
    assert (pipeline / "research_assets.json").exists()
    assert not (pipeline / "direction_tts.json").exists()
    assert not (pipeline / "compiled.json").exists()
