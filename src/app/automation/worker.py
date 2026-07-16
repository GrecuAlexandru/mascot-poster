from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.automation.checkpoints import invalidate_checkpoints
from app.automation.job_service import JobService
from app.automation.models import AutomationJob
from app.domain.models import GenerationRequest
from app.services.video_generation_service import format_exception_message


class GenerationWorker:
    def __init__(
        self,
        job_service: JobService,
        generator: Any,
        worker_id: str,
        lease_seconds: int = 300,
        default_voice_ids: dict[str, str] | None = None,
    ):
        self.job_service = job_service
        self.generator = generator
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.default_voice_ids = default_voice_ids or {}

    async def run_once(self) -> AutomationJob | None:
        job = self.job_service.claim_next(self.worker_id, self.lease_seconds)
        if job is None:
            return None
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            invalidate_checkpoints(
                Path(self.generator.output_base),
                job.id,
                job.regeneration_kind,
            )
            request = GenerationRequest(
                topic_override=job.topic_override,
                language=job.language,
                target_duration_seconds=job.target_duration_seconds,
                voice_id=job.voice_id or self.default_voice_ids.get(job.language),
            )
            result = await self.generator.generate(request, job_id=job.id)
            topic, caption = self._read_metadata(result.render_result.video_path, job)
            return self.job_service.complete_generation(
                job.id,
                Path(result.render_result.video_path),
                caption=caption,
                topic=topic,
            )
        except Exception as error:
            return self.job_service.fail(job.id, format_exception_message(error))
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def run_forever(self, poll_seconds: float = 5.0) -> None:
        while True:
            result = await self.run_once()
            if result is None:
                await asyncio.sleep(poll_seconds)

    async def _heartbeat(self, job_id: str) -> None:
        interval = max(10, self.lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            self.job_service.extend_lease(job_id, self.worker_id, self.lease_seconds)

    @staticmethod
    def _read_metadata(video_path: Path, job: AutomationJob) -> tuple[str, str]:
        pipeline_dir = Path(video_path).parent / "_pipeline"
        topic_payload = GenerationWorker._load_json(pipeline_dir / "topic.json")
        script_payload = GenerationWorker._load_json(
            pipeline_dir / "script_verification.json"
        ).get("script", {})
        topic = str(
            script_payload.get("title")
            or topic_payload.get("title")
            or job.topic_override
            or "Untitled video"
        )
        caption = str(script_payload.get("caption") or topic)
        hashtags = [str(item) for item in script_payload.get("hashtags", []) if item]
        if hashtags:
            caption = f"{caption}\n\n{' '.join(hashtags)}"
        return topic, caption

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
