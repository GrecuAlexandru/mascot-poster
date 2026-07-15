from __future__ import annotations

import asyncio

from app.automation.database import AutomationDatabase
from app.automation.job_service import JobService
from app.automation.settings import get_automation_settings
from app.config import get_settings
from app.services.reference_generation_factory import build_reference_generation_service


def build_job_service() -> JobService:
    settings = get_automation_settings()
    database = AutomationDatabase(settings.database_url)
    database.create_schema()
    return JobService(database)


def build_publication_service(job_service: JobService):
    from app.automation.buffer_client import BufferClient
    from app.automation.publisher import PublicationService
    from app.automation.r2_storage import R2Storage

    settings = get_automation_settings()
    required = [
        settings.r2_endpoint_url,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket,
        settings.r2_public_base_url,
        settings.buffer_api_token,
        settings.buffer_tiktok_channel_id,
    ]
    if not all(required):
        return None
    r2 = R2Storage(
        endpoint_url=settings.r2_endpoint_url or "",
        access_key_id=settings.r2_access_key_id.get_secret_value(),
        secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        bucket=settings.r2_bucket or "",
        public_base_url=settings.r2_public_base_url or "",
    )
    buffer = BufferClient(settings.buffer_api_token.get_secret_value())
    return PublicationService(
        job_service,
        r2,
        buffer,
        channel_id=settings.buffer_tiktok_channel_id or "",
        object_prefix=settings.r2_object_prefix,
        thumbnail_offset_ms=settings.buffer_thumbnail_offset_ms,
    )


async def run_generation_worker() -> None:
    from app.automation.worker import GenerationWorker

    automation = get_automation_settings()
    generator = build_reference_generation_service(get_settings())
    worker = GenerationWorker(
        build_job_service(),
        generator,
        worker_id=automation.worker_id,
        lease_seconds=automation.worker_lease_seconds,
    )
    await worker.run_forever(automation.worker_poll_seconds)


def main() -> None:
    asyncio.run(run_generation_worker())


if __name__ == "__main__":
    main()
