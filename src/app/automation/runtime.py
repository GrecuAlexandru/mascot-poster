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
