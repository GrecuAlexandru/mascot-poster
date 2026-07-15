from __future__ import annotations

import asyncio

from app.automation.cleanup import CleanupService
from app.automation.runtime import build_job_service, build_publication_service
from app.automation.settings import get_automation_settings
from app.config import get_settings


async def run() -> None:
    automation = get_automation_settings()
    job_service = build_job_service()
    publisher = build_publication_service(job_service)
    if publisher is None:
        raise RuntimeError("R2 and Buffer configuration is required")
    output_base = get_settings().project_root / "output" / "jobs"
    cleanup = CleanupService(job_service, publisher.r2, output_base)
    while True:
        cleanup.run_once()
        await asyncio.sleep(automation.cleanup_poll_seconds)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
