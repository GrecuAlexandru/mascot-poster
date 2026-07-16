from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.automation.database import AutomationDatabase
from app.automation.job_service import InvalidTransition, JobService
from app.automation.models import JobState
from app.automation.publisher import PublicationService
from app.automation.buffer_client import BufferPost


class FakeR2:
    def __init__(self):
        self.uploads = []

    def upload_video(self, source: Path, object_key: str) -> str:
        self.uploads.append((source, object_key))
        return f"https://media.example.test/{object_key}"


class FakeBuffer:
    def __init__(self, status: str = "scheduled"):
        self.status = status
        self.creates = []
        self.reads = []

    async def create_video_post(self, **kwargs) -> BufferPost:
        self.creates.append(kwargs)
        return BufferPost(id="buffer-123", status=self.status)

    async def get_post(self, post_id: str) -> BufferPost:
        self.reads.append(post_id)
        return BufferPost(id=post_id, status=self.status)


def build_service(tmp_path: Path) -> JobService:
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    return JobService(database)


def approved_job(service: JobService, tmp_path: Path, target_at: datetime):
    job = service.create_job(target_at=target_at)
    service.claim_next("worker")
    video = tmp_path / f"{job.id}.mp4"
    video.write_bytes(b"approved-video")
    ready = service.complete_generation(job.id, video, "Caption #tag", "Topic")
    return service.approve(
        ready.id,
        ready.video_sha256 or "",
        telegram_user_id=7,
        telegram_chat_id=8,
        now=min(target_at, datetime.now(timezone.utc)),
    )


def test_only_approved_hash_can_be_staged(tmp_path: Path):
    service = build_service(tmp_path)
    job = service.create_job(
        target_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    publisher = PublicationService(service, FakeR2(), FakeBuffer(), "channel-1")

    with pytest.raises(InvalidTransition, match="approved"):
        asyncio.run(publisher.publish(job.id))


def test_tampered_video_is_never_uploaded(tmp_path: Path):
    service = build_service(tmp_path)
    target = datetime.now(timezone.utc) + timedelta(hours=2)
    job = approved_job(service, tmp_path, target)
    Path(job.video_path).write_bytes(b"tampered")
    r2 = FakeR2()
    publisher = PublicationService(service, r2, FakeBuffer(), "channel-1")

    with pytest.raises(InvalidTransition, match="hash"):
        asyncio.run(publisher.publish(job.id, now=datetime.now(timezone.utc)))

    assert r2.uploads == []


def test_future_approved_video_is_custom_scheduled_in_buffer(tmp_path: Path):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    target = now + timedelta(hours=2)
    job = approved_job(service, tmp_path, target)
    r2 = FakeR2()
    buffer = FakeBuffer()
    publisher = PublicationService(service, r2, buffer, "channel-1")

    result = asyncio.run(publisher.publish(job.id, now=now))

    assert result.state is JobState.SCHEDULED
    assert result.buffer_post_id == "buffer-123"
    assert len(r2.uploads) == 1
    assert buffer.creates[0]["mode"] == "customScheduled"
    assert buffer.creates[0]["due_at"] == target
    assert buffer.creates[0]["is_ai_generated"] is True


def test_publish_uses_renderer_thumbnail_offset_metadata(tmp_path: Path):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    target = now + timedelta(hours=2)
    job = approved_job(service, tmp_path, target)
    Path(job.video_path).with_name("thumbnail.json").write_text(
        '{"thumbnail_offset_ms": 24750}',
        encoding="utf-8",
    )
    buffer = FakeBuffer()
    publisher = PublicationService(
        service,
        FakeR2(),
        buffer,
        "channel-1",
        thumbnail_offset_ms=2000,
    )

    asyncio.run(publisher.publish(job.id, now=now))

    assert buffer.creates[0]["thumbnail_offset_ms"] == 24750


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        "not-json",
        '{"thumbnail_offset_ms": "24750"}',
        '{"thumbnail_offset_ms": true}',
        '{"thumbnail_offset_ms": -1}',
    ],
)
def test_publish_falls_back_for_missing_or_invalid_thumbnail_metadata(
    tmp_path: Path, metadata: str | None
):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    job = approved_job(service, tmp_path, now + timedelta(hours=2))
    if metadata is not None:
        Path(job.video_path).with_name("thumbnail.json").write_text(
            metadata,
            encoding="utf-8",
        )
    buffer = FakeBuffer()
    publisher = PublicationService(
        service,
        FakeR2(),
        buffer,
        "channel-1",
        thumbnail_offset_ms=2000,
    )

    asyncio.run(publisher.publish(job.id, now=now))

    assert buffer.creates[0]["thumbnail_offset_ms"] == 2000


def test_approval_after_target_but_within_window_shares_now(tmp_path: Path):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=1)
    job = approved_job(service, tmp_path, target)
    buffer = FakeBuffer(status="sending")
    publisher = PublicationService(service, FakeR2(), buffer, "channel-1")

    result = asyncio.run(publisher.publish(job.id, now=now))

    assert result.state is JobState.PUBLISHING
    assert buffer.creates[0]["mode"] == "shareNow"
    assert buffer.creates[0]["due_at"] is None


def test_publish_is_idempotent_after_buffer_accepts_job(tmp_path: Path):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    job = approved_job(service, tmp_path, now + timedelta(hours=1))
    buffer = FakeBuffer()
    publisher = PublicationService(service, FakeR2(), buffer, "channel-1")

    first = asyncio.run(publisher.publish(job.id, now=now))
    second = asyncio.run(publisher.publish(job.id, now=now))

    assert first.buffer_post_id == second.buffer_post_id
    assert len(buffer.creates) == 1


def test_reconciliation_marks_sent_and_sets_retention(tmp_path: Path):
    service = build_service(tmp_path)
    now = datetime.now(timezone.utc)
    job = approved_job(service, tmp_path, now + timedelta(hours=1))
    buffer = FakeBuffer(status="scheduled")
    publisher = PublicationService(service, FakeR2(), buffer, "channel-1")
    scheduled = asyncio.run(publisher.publish(job.id, now=now))
    buffer.status = "sent"

    published = asyncio.run(
        publisher.reconcile(scheduled.id, now=now + timedelta(hours=1, minutes=1))
    )

    assert published.state is JobState.PUBLISHED
    assert published.published_at is not None
    assert published.r2_delete_after == now + timedelta(hours=49, minutes=1)
    assert published.local_delete_after == now + timedelta(days=30, hours=1, minutes=1)
