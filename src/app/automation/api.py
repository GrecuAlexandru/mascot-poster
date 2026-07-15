from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from app.automation.job_service import JobNotFound, JobService
from app.automation.models import AutomationJob


class CreateAutomationJob(BaseModel):
    target_at: datetime
    topic_override: str | None = Field(default=None, max_length=500)
    language: str = Field(default="ro", pattern="^(ro|en)$")
    target_duration_seconds: int = Field(default=25, ge=20, le=60)
    voice_id: str | None = Field(default=None, max_length=200)

    @field_validator("target_at")
    @classmethod
    def target_must_be_in_the_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("target_at must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("target_at must be in the future")
        return value


def create_automation_router(
    job_service: JobService,
    api_token: str,
    publisher=None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/automation", tags=["automation"])
    bearer = HTTPBearer(auto_error=False)

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
        response_model=AutomationJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authorize)],
    )
    def create_job(payload: CreateAutomationJob) -> AutomationJob:
        return job_service.create_job(
            target_at=payload.target_at,
            topic_override=payload.topic_override,
            language=payload.language,
            target_duration_seconds=payload.target_duration_seconds,
            voice_id=payload.voice_id,
        )

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
