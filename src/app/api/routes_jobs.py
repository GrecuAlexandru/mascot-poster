from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.schemas import (
    AnalyticsSnapshot,
    ApproveRequest,
    CostResponse,
    CreateJobRequest,
    CreateTopicRequest,
    JobResponse,
    JobStatus,
    PublicationPayload,
    RejectRequest,
    RenderRequest,
    TopicIdeaCandidate,
    TopicIdeaRequest,
    TopicIdeaResponse,
)
from app.config import get_settings, get_topic_history_service, get_topic_llm_provider
from app.domain.models import TopicSpec
from app.providers.llm.base import LLMError
from app.services.pipeline import PipelineOrchestrator, Stage

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="Automated Short Video Platform",
    version="0.1.0",
    description="API for generating comparison videos for TikTok, YouTube Shorts, and Instagram Reels",
)

_jobs: dict[str, dict] = {}


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


def _get_orchestrator() -> PipelineOrchestrator:
    settings = get_settings()
    return PipelineOrchestrator(
        templates_dir=settings.templates_dir,
        mascots_dir=settings.mascots_dir,
        output_base=PROJECT_ROOT / "output" / "jobs",
        font_path=settings.resolve_font(),
        ffmpeg_bin=settings.ffmpeg_bin,
        ffprobe_bin=settings.ffprobe_bin,
        fps=settings.video_fps,
        width=settings.video_width,
        height=settings.video_height,
        audio_sample_rate=settings.audio_sample_rate,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    settings = get_settings()
    checks = {
        "templates_dir": settings.templates_dir.exists(),
        "mascots_dir": settings.mascots_dir.exists(),
        "ffmpeg": _check_binary(settings.ffmpeg_bin),
        "ffprobe": _check_binary(settings.ffprobe_bin),
    }
    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"ready": all_ok, "checks": checks},
    )


@app.get("/metrics")
async def metrics():
    total = len(_jobs)
    by_status: dict[str, int] = {}
    for j in _jobs.values():
        s = j.get("status", "UNKNOWN")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "total_jobs": total,
        "by_status": by_status,
    }


@app.post("/api/v1/jobs", response_model=JobResponse)
async def create_job(req: CreateJobRequest):
    orch = _get_orchestrator()

    topic: Optional[TopicSpec] = None
    if req.topic_left and req.topic_right:
        topic = TopicSpec(
            title=req.title or f"{req.topic_left} vs {req.topic_right}",
            comparison_left=req.topic_left,
            comparison_right=req.topic_right,
            angle=req.topic_angle or "",
        )

    state = orch.create_job(topic=topic)
    _jobs[state.job_id] = {
        "status": "QUEUED",
        "stage": state.current_stage.value,
        "state": state,
        "created_at": str(__import__("datetime").datetime.now()),
    }

    return JobResponse(job_id=state.job_id, status="QUEUED")


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    state = job["state"]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        current_stage=state.current_stage.value,
        error_message=state.error_message,
        retry_count=state.retry_count,
        created_at=job.get("created_at"),
    )


@app.post("/api/v1/jobs/{job_id}/approve", response_model=JobResponse)
async def approve_job(job_id: str, req: ApproveRequest):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    job["status"] = "APPROVED"
    job["state"].checkpoint(Stage.APPROVED)
    return JobResponse(job_id=job_id, status="APPROVED")


@app.post("/api/v1/jobs/{job_id}/reject", response_model=JobResponse)
async def reject_job(job_id: str, req: RejectRequest):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    job["status"] = "REJECTED"
    job["state"].checkpoint(Stage.REJECTED)
    return JobResponse(job_id=job_id, status="REJECTED")


@app.post("/api/v1/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    state = job["state"]
    state.retry_count += 1
    job["status"] = "QUEUED"
    return JobResponse(job_id=job_id, status="QUEUED")


@app.post("/api/v1/topics/generate", response_model=TopicIdeaResponse)
async def generate_topic_idea(req: TopicIdeaRequest):
    from app.services.topic_service import TopicService

    history = get_topic_history_service()

    llm = get_topic_llm_provider()
    if not llm:
        from app.config import get_llm_provider
        llm = get_llm_provider()

    if not llm:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured. Set OPENROUTER_API_KEY in .env",
        )

    svc = TopicService(llm_provider=llm)

    try:
        candidates = await svc.generate_unique_topics(
            niche=req.niche or "",
            language=req.language,
            history=history,
            count=req.count,
            blacklist=req.blacklist,
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="No unique topic could be generated. Try changing the niche.",
        )

    best = candidates[0]
    topic = TopicSpec(
        title=best.title,
        comparison_left=best.left,
        comparison_right=best.right,
        angle=best.angle,
    )

    orch = _get_orchestrator()
    state = orch.create_job(topic=topic)
    _jobs[state.job_id] = {
        "status": "QUEUED",
        "stage": state.current_stage.value,
        "state": state,
        "created_at": str(__import__("datetime").datetime.now()),
    }

    history.add_from_topic(topic, job_id=state.job_id)

    candidate = TopicIdeaCandidate(
        title=best.title,
        left=best.left,
        right=best.right,
        angle=best.angle,
        why_it_might_work=best.why_it_might_work,
        risk_level=best.risk_level,
    )

    return TopicIdeaResponse(
        job_id=state.job_id,
        status="QUEUED",
        candidate=candidate,
        total_in_history=history.count,
    )


@app.post("/api/v1/topics", response_model=JobResponse)
async def create_topic(req: CreateTopicRequest):
    from app.services.topic_service import TopicService

    svc = TopicService()
    topic = svc.create_manual_topic(
        left=req.left, right=req.right, angle=req.angle, title=req.title
    )
    orch = _get_orchestrator()
    state = orch.create_job(topic=topic)
    _jobs[state.job_id] = {
        "status": "QUEUED",
        "stage": state.current_stage.value,
        "state": state,
        "created_at": str(__import__("datetime").datetime.now()),
    }
    return JobResponse(job_id=state.job_id, status="QUEUED")


@app.post("/api/v1/render")
async def render_from_spec(req: RenderRequest):
    spec_path = Path(req.spec_path)
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail=f"Spec not found: {spec_path}")

    output_dir = Path(req.output_dir) if req.output_dir else PROJECT_ROOT / "output" / "render_api"

    from app.domain.models import RenderSpec
    from app.services.render_service import RenderService

    settings = get_settings()
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    for key in ("left_image", "right_image", "audio"):
        if key in spec_data and not Path(spec_data[key]).is_absolute():
            spec_data[key] = str(PROJECT_ROOT / spec_data[key])
    spec = RenderSpec(**spec_data)

    svc = RenderService(
        templates_dir=settings.templates_dir,
        mascots_dir=settings.mascots_dir,
        font_path=settings.resolve_font(),
        ffmpeg_bin=settings.ffmpeg_bin,
        ffprobe_bin=settings.ffprobe_bin,
        fps=settings.video_fps,
        width=settings.video_width,
        height=settings.video_height,
        audio_sample_rate=settings.audio_sample_rate,
    )
    result = svc.render(spec, output_dir)
    return {
        "video_path": str(result.video_path),
        "poster_path": str(result.poster_path),
        "duration": result.duration_seconds,
        "scenes": result.scene_count,
    }


@app.get("/api/v1/jobs/{job_id}/cost", response_model=CostResponse)
async def get_job_cost(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    state = _jobs[job_id]["state"]
    return CostResponse(
        job_id=job_id,
        total_cost_usd=state.cost_tracker.total_cost,
        by_category=state.cost_tracker.to_dict()["by_category"],
    )


@app.post("/api/v1/jobs/{job_id}/publish")
async def publish_job(job_id: str, payload: PublicationPayload):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    job["status"] = "PUBLISHING"
    job["publication"] = payload.model_dump()
    return {"job_id": job_id, "status": "PUBLISHING", "platform": payload.platform}


@app.post("/api/v1/jobs/{job_id}/analytics")
async def record_analytics(job_id: str, snapshot: AnalyticsSnapshot):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    job.setdefault("analytics", []).append(snapshot.model_dump())
    return {"job_id": job_id, "status": "recorded"}


def _check_binary(name: str) -> bool:
    import subprocess
    try:
        result = subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
