from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.automation.cleanup import CleanupService
from app.automation.database import AutomationDatabase, AutomationJobRow
from app.automation.job_service import JobService


class FakeR2:
    def __init__(self):
        self.deleted = []

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


def test_cleanup_deletes_only_due_r2_and_scoped_local_job_directory(tmp_path: Path):
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    service = JobService(database)
    now = datetime.now(timezone.utc)
    output_base = tmp_path / "jobs"
    job = service.create_job(target_at=now + timedelta(hours=1))
    job_dir = output_base / job.id
    job_dir.mkdir(parents=True)
    video = job_dir / "video.mp4"
    video.write_bytes(b"video")
    with database.session() as session:
        row = session.get(AutomationJobRow, job.id)
        row.r2_object_key = f"buffer/{job.id}/video.mp4"
        row.r2_delete_after = now - timedelta(seconds=1)
        row.local_delete_after = now - timedelta(seconds=1)
        row.video_path = str(video)
    r2 = FakeR2()

    cleaned = CleanupService(service, r2, output_base).run_once(now=now)

    assert cleaned == 1
    assert r2.deleted == [f"buffer/{job.id}/video.mp4"]
    assert not job_dir.exists()
    stored = service.get(job.id)
    assert stored.r2_object_key is None
    assert stored.video_path is None
