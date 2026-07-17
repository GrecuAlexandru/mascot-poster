from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator, model_validator

from app.automation.idea_queue_service import IdeaQueueService
from app.automation.job_service import JobNotFound, JobService
from app.automation.models import (
    AutomationJob,
    IdeaDraft,
    IdeaHistoryExport,
    IdeaImportResult,
    JobState,
)


class CreateAutomationJob(BaseModel):
    target_at: datetime
    topic_override: str | None = Field(default=None, max_length=500)
    language: str = Field(default="ro", pattern="^(ro|en)$")
    target_duration_seconds: int = Field(default=25, ge=20, le=60)
    voice_id: str | None = Field(default=None, max_length=200)
    use_next_idea: bool = False

    @field_validator("target_at")
    @classmethod
    def target_must_be_in_the_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("target_at must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("target_at must be in the future")
        return value

    @model_validator(mode="after")
    def queue_and_override_are_exclusive(self):
        if self.use_next_idea and self.topic_override:
            raise ValueError("topic_override cannot be combined with use_next_idea")
        return self


class CreateAutomationJobResult(BaseModel):
    status: Literal["CREATED", "NO_IDEA_AVAILABLE"]
    job: AutomationJob | None


class ImportIdeasRequest(BaseModel):
    ideas: list[IdeaDraft] = Field(max_length=100)


def create_automation_router(
    job_service: JobService,
    api_token: str,
    publisher=None,
    idea_queue: IdeaQueueService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/automation", tags=["automation"])
    bearer = HTTPBearer(auto_error=False)
    idea_queue = idea_queue or IdeaQueueService(job_service.database)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        supplied = credentials.credentials if credentials else ""
        if not api_token or not hmac.compare_digest(supplied, api_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid automation API token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @router.post(
        "/jobs",
        response_model=CreateAutomationJobResult,
        dependencies=[Depends(authorize)],
    )
    def create_job(
        payload: CreateAutomationJob,
        response: Response,
    ) -> CreateAutomationJobResult:
        if payload.use_next_idea:
            job = job_service.create_job_from_next_idea(
                target_at=payload.target_at,
                language=payload.language,
                target_duration_seconds=payload.target_duration_seconds,
                voice_id=payload.voice_id,
            )
        else:
            job = job_service.create_job(
                target_at=payload.target_at,
                topic_override=payload.topic_override,
                language=payload.language,
                target_duration_seconds=payload.target_duration_seconds,
                voice_id=payload.voice_id,
            )
        if job is None:
            return CreateAutomationJobResult(status="NO_IDEA_AVAILABLE", job=None)
        response.status_code = status.HTTP_201_CREATED
        return CreateAutomationJobResult(status="CREATED", job=job)

    @router.post(
        "/ideas/import",
        response_model=IdeaImportResult,
        dependencies=[Depends(authorize)],
    )
    def import_ideas(payload: ImportIdeasRequest) -> IdeaImportResult:
        return idea_queue.import_ideas(payload.ideas)

    @router.get(
        "/ideas/history",
        response_model=IdeaHistoryExport,
        dependencies=[Depends(authorize)],
    )
    def export_idea_history() -> IdeaHistoryExport:
        return idea_queue.export_history()

    @router.get(
        "/jobs",
        response_model=list[AutomationJob],
        dependencies=[Depends(authorize)],
    )
    def list_jobs(states: str = "") -> list[AutomationJob]:
        try:
            selected = {
                JobState(item.strip()) for item in states.split(",") if item.strip()
            }
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid job state") from error
        return job_service.list_by_states(selected) if selected else job_service.list_active()

    @router.get(
        "/jobs/{job_id}",
        response_model=AutomationJob,
        dependencies=[Depends(authorize)],
    )
    def get_job(job_id: str) -> AutomationJob:
        try:
            return job_service.get(job_id)
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @router.post(
        "/jobs/{job_id}/publish",
        response_model=AutomationJob,
        dependencies=[Depends(authorize)],
    )
    async def publish_job(job_id: str) -> AutomationJob:
        if publisher is None:
            raise HTTPException(status_code=503, detail="publishing is not configured")
        try:
            return await publisher.publish(job_id)
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except Exception as error:
            from app.automation.job_service import InvalidTransition

            if isinstance(error, InvalidTransition):
                raise HTTPException(status_code=409, detail=str(error)) from error
            raise

    @router.post(
        "/jobs/{job_id}/reconcile",
        response_model=AutomationJob,
        dependencies=[Depends(authorize)],
    )
    async def reconcile_job(job_id: str) -> AutomationJob:
        if publisher is None:
            raise HTTPException(status_code=503, detail="publishing is not configured")
        try:
            return await publisher.reconcile(job_id)
        except JobNotFound as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    return router
