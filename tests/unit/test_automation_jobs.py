from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.automation.database import AutomationDatabase
from app.automation.job_service import InvalidTransition, JobService
from app.automation.models import JobState, RegenerationKind


@pytest.fixture
def job_service(tmp_path: Path) -> JobService:
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    return JobService(database)


def utc(hour: int) -> datetime:
    return datetime(2026, 7, 15, hour, tzinfo=timezone.utc)


def ready_job(job_service: JobService, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"approved video")
    job = job_service.create_job(target_at=utc(9), topic_override="Cafea vs ceai")
    claimed = job_service.claim_next("test-worker", lease_seconds=60)
    assert claimed is not None and claimed.id == job.id
    return job_service.complete_generation(
        job.id,
        video_path=video,
        caption="Cafea sau ceai?",
        topic="Cafea vs ceai",
    )


def test_claim_next_is_atomic_and_leased(job_service: JobService) -> None:
    first = job_service.create_job(target_at=utc(9))
    job_service.create_job(target_at=utc(17))

    claimed = job_service.claim_next("worker-1", lease_seconds=60)
    second_claim = job_service.claim_next("worker-2", lease_seconds=60)

    assert claimed is not None and claimed.id == first.id
    assert claimed.state is JobState.RUNNING
    assert claimed.lease_owner == "worker-1"
    assert second_claim is not None and second_claim.id != claimed.id


def test_approval_binds_hash_and_is_idempotent(
    job_service: JobService, tmp_path: Path
) -> None:
    job = ready_job(job_service, tmp_path)

    approved = job_service.approve(
        job.id,
        expected_video_sha256=job.video_sha256,
        telegram_user_id=7,
        telegram_chat_id=9,
    )
    repeated = job_service.approve(
        job.id,
        expected_video_sha256=job.video_sha256,
        telegram_user_id=7,
        telegram_chat_id=9,
    )

    assert approved.state is JobState.APPROVED
    assert approved.approved_video_sha256 == job.video_sha256
    assert repeated.approval_id == approved.approval_id


def test_approval_rejects_wrong_video_hash(
    job_service: JobService, tmp_path: Path
) -> None:
    job = ready_job(job_service, tmp_path)

    with pytest.raises(InvalidTransition, match="video hash"):
        job_service.approve(job.id, "wrong", 7, 9)


def test_regeneration_invalidates_approval(
    job_service: JobService, tmp_path: Path
) -> None:
    job = ready_job(job_service, tmp_path)
    job_service.approve(job.id, job.video_sha256, 7, 9)

    regenerated = job_service.request_regeneration(
        job.id, RegenerationKind.IMAGES
    )

    assert regenerated.state is JobState.QUEUED
    assert regenerated.regeneration_kind is RegenerationKind.IMAGES
    assert regenerated.approved_video_sha256 is None
    assert regenerated.video_sha256 is None


def test_ready_job_can_be_rejected_but_published_job_cannot(
    job_service: JobService, tmp_path: Path
) -> None:
    ready = ready_job(job_service, tmp_path)
    rejected = job_service.reject(ready.id, "Not strong enough", 7, 9)
    assert rejected.state is JobState.REJECTED

    with pytest.raises(InvalidTransition):
        job_service.approve(rejected.id, ready.video_sha256, 7, 9)


def test_unapproved_overdue_job_becomes_missed(
    job_service: JobService, tmp_path: Path
) -> None:
    ready = ready_job(job_service, tmp_path)

    missed = job_service.mark_missed(
        ready.id, now=ready.target_at + timedelta(hours=3, seconds=1)
    )

    assert missed.state is JobState.MISSED


def test_cancel_only_stops_prepublication_jobs(job_service: JobService) -> None:
    queued = job_service.create_job(target_at=utc(9))
    cancelled = job_service.cancel(queued.id)
    assert cancelled.state is JobState.CANCELLED

    with pytest.raises(InvalidTransition):
        job_service.cancel(cancelled.id)
