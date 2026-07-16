from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.automation.job_service import InvalidTransition, JobService
from app.automation.models import AutomationJob, JobState


class PublicationService:
    def __init__(
        self,
        job_service: JobService,
        r2: Any,
        buffer: Any,
        channel_id: str,
        object_prefix: str = "buffer",
        thumbnail_offset_ms: int = 2000,
    ):
        self.job_service = job_service
        self.r2 = r2
        self.buffer = buffer
        self.channel_id = channel_id
        self.object_prefix = object_prefix.strip("/")
        self.thumbnail_offset_ms = thumbnail_offset_ms

    async def publish(
        self,
        job_id: str,
        now: datetime | None = None,
    ) -> AutomationJob:
        now = now or datetime.now(timezone.utc)
        job = self.job_service.get(job_id)
        if job.buffer_post_id:
            return job
        if job.state is not JobState.APPROVED:
            raise InvalidTransition("job is not approved")
        video_path = Path(job.video_path or "")
        if not video_path.is_file():
            raise InvalidTransition("approved video does not exist")
        digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
        if digest != job.approved_video_sha256:
            raise InvalidTransition("approved video hash no longer matches")
        self.job_service.begin_media_staging(job.id)
        try:
            object_key = (
                f"{self.object_prefix}/{job.id}/{job.approved_video_sha256}.mp4"
            )
            public_url = self.r2.upload_video(video_path, object_key)
            self.job_service.record_staged_media(job.id, object_key, public_url)
            target_at = self._as_utc(job.target_at)
            current = self._as_utc(now)
            mode = "customScheduled" if current < target_at else "shareNow"
            due_at = target_at if mode == "customScheduled" else None
            thumbnail_offset_ms = self._thumbnail_offset(video_path)
            post = await self.buffer.create_video_post(
                channel_id=self.channel_id,
                text=job.caption or job.topic or "",
                video_url=public_url,
                mode=mode,
                due_at=due_at,
                is_ai_generated=True,
                thumbnail_offset_ms=thumbnail_offset_ms,
            )
            return self.job_service.record_buffer_post(
                job.id,
                post_id=post.id,
                buffer_status=post.status,
                now=current,
            )
        except Exception as error:
            self.job_service.fail(job.id, f"{type(error).__name__}: {error}")
            raise

    async def reconcile(
        self,
        job_id: str,
        now: datetime | None = None,
    ) -> AutomationJob:
        job = self.job_service.get(job_id)
        if not job.buffer_post_id:
            raise InvalidTransition("job has no Buffer post")
        post = await self.buffer.get_post(job.buffer_post_id)
        return self.job_service.update_buffer_status(
            job.id,
            buffer_status=post.status,
            error_message=post.error,
            published_at=post.sent_at,
            now=now,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _thumbnail_offset(self, video_path: Path) -> int:
        metadata_path = video_path.with_name("thumbnail.json")
        if not metadata_path.is_file():
            return self.thumbnail_offset_ms
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            value = payload["thumbnail_offset_ms"]
        except (KeyError, TypeError, json.JSONDecodeError, OSError):
            return self.thumbnail_offset_ms
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return self.thumbnail_offset_ms
        return value
