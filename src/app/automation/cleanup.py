from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.automation.job_service import JobService


class CleanupService:
    def __init__(self, job_service: JobService, r2: Any, output_base: Path):
        self.job_service = job_service
        self.r2 = r2
        self.output_base = Path(output_base).resolve()

    def run_once(self, now: datetime | None = None) -> int:
        cleaned = 0
        for job in self.job_service.list_cleanup_due(now=now):
            r2_deleted = False
            local_deleted = False
            if job.r2_object_key and job.r2_delete_after:
                self.r2.delete(job.r2_object_key)
                r2_deleted = True
            if job.video_path and job.local_delete_after:
                local_deleted = self._delete_local_job(job.id)
            if r2_deleted or local_deleted:
                self.job_service.record_cleanup(
                    job.id,
                    r2_deleted=r2_deleted,
                    local_deleted=local_deleted,
                )
                cleaned += 1
        return cleaned

    def _delete_local_job(self, job_id: str) -> bool:
        target = (self.output_base / job_id).resolve()
        if target.parent != self.output_base or target.name != job_id:
            raise RuntimeError("refusing to delete an unscoped job path")
        if target.is_dir():
            shutil.rmtree(target)
        return not target.exists()
