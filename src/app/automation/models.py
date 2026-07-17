from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    STAGING_MEDIA = "STAGING_MEDIA"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    MISSED = "MISSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RegenerationKind(str, Enum):
    SCRIPT = "SCRIPT"
    IMAGES = "IMAGES"
    FULL = "FULL"


class IdeaState(str, Enum):
    QUEUED = "QUEUED"
    CONSUMED = "CONSUMED"


class IdeaDraft(BaseModel):
    idea_id: Optional[str] = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    left: str = Field(min_length=1, max_length=200)
    right: str = Field(min_length=1, max_length=200)
    angle: str = Field(default="", max_length=2000)


class AutomationIdea(BaseModel):
    id: str
    idea_id: Optional[str] = None
    title: str
    left: str
    right: str
    angle: str = ""
    state: IdeaState
    created_at: datetime
    consumed_at: Optional[datetime] = None
    automation_job_id: Optional[str] = None


class SkippedIdea(BaseModel):
    idea_id: Optional[str] = None
    title: str
    reason: str


class IdeaImportResult(BaseModel):
    accepted: list[AutomationIdea]
    skipped: list[SkippedIdea]


class IdeaHistoryEntry(BaseModel):
    title: str
    left: str = ""
    right: str = ""
    source: str


class IdeaHistoryExport(BaseModel):
    used: list[IdeaHistoryEntry]
    queued: list[IdeaHistoryEntry]
    legacy: list[IdeaHistoryEntry]
    markdown: str


class AutomationJob(BaseModel):
    id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    target_at: datetime
    topic_override: Optional[str] = None
    idea_id: Optional[str] = None
    language: str = "ro"
    target_duration_seconds: int = 25
    voice_id: Optional[str] = None
    regeneration_kind: Optional[RegenerationKind] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    topic: Optional[str] = None
    caption: Optional[str] = None
    video_path: Optional[Path] = None
    video_sha256: Optional[str] = None
    approval_id: Optional[str] = None
    approved_video_sha256: Optional[str] = None
    approved_at: Optional[datetime] = None
    telegram_user_id: Optional[int] = None
    telegram_chat_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    telegram_notified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    error_message: Optional[str] = None
    action_token: Optional[str] = None
    r2_object_key: Optional[str] = None
    r2_public_url: Optional[str] = None
    buffer_post_id: Optional[str] = None
    buffer_status: Optional[str] = None
    published_at: Optional[datetime] = None
    r2_delete_after: Optional[datetime] = None
    local_delete_after: Optional[datetime] = None
