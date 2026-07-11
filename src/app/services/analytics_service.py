from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AnalyticsSnapshot(BaseModel):
    job_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    average_watch_time: Optional[float] = None
    completion_rate: Optional[float] = None
    follower_increase: int = 0
    revenue: Optional[float] = None
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AnalyticsService:
    def __init__(self, storage_dir: Optional[Path] = None):
        self._storage_dir = storage_dir
        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, list[AnalyticsSnapshot]] = {}

    def record(self, snapshot: AnalyticsSnapshot) -> None:
        job_id = snapshot.job_id
        if job_id not in self._snapshots:
            self._snapshots[job_id] = []
        self._snapshots[job_id].append(snapshot)
        logger.info(
            f"Analytics recorded: job={job_id}, platform={snapshot.platform}, "
            f"views={snapshot.views}"
        )
        if self._storage_dir:
            self._persist(snapshot)

    def get_snapshots(self, job_id: str) -> list[AnalyticsSnapshot]:
        return self._snapshots.get(job_id, [])

    def get_latest(self, job_id: str) -> Optional[AnalyticsSnapshot]:
        snapshots = self._snapshots.get(job_id, [])
        return snapshots[-1] if snapshots else None

    def aggregate(self, job_id: str) -> dict:
        snapshots = self._snapshots.get(job_id, [])
        if not snapshots:
            return {"job_id": job_id, "platforms": {}}

        by_platform: dict[str, dict] = {}
        for s in snapshots:
            p = s.platform
            if p not in by_platform:
                by_platform[p] = {
                    "views": 0, "likes": 0, "comments": 0, "shares": 0,
                    "saves": 0, "follower_increase": 0, "snapshots": 0,
                }
            d = by_platform[p]
            d["views"] = max(d["views"], s.views)
            d["likes"] = max(d["likes"], s.likes)
            d["comments"] = max(d["comments"], s.comments)
            d["shares"] = max(d["shares"], s.shares)
            d["saves"] = max(d["saves"], s.saves)
            d["follower_increase"] += s.follower_increase
            d["snapshots"] += 1
            if s.revenue is not None:
                d["revenue"] = s.revenue

        return {"job_id": job_id, "platforms": by_platform}

    def get_daily_summary(self) -> dict:
        total_jobs = len(self._snapshots)
        total_views = sum(
            s.views for snapshots in self._snapshots.values()
            for s in snapshots
        )
        return {
            "total_jobs": total_jobs,
            "total_views": total_views,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }

    def _persist(self, snapshot: AnalyticsSnapshot) -> None:
        if not self._storage_dir:
            return
        path = self._storage_dir / f"{snapshot.job_id}_{snapshot.platform}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(snapshot.model_dump_json() + "\n")

    def get_performance_topics(self, min_views: int = 1000) -> list[str]:
        good_jobs = [
            job_id
            for job_id, snapshots in self._snapshots.items()
            if any(s.views >= min_views for s in snapshots)
        ]
        return good_jobs
