from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


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


class AutomationJob(BaseModel):
    id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    target_at: datetime
    topic_override: Optional[str] = None
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
