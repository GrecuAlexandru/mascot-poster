from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    channel_id: Optional[str] = None
    topic_id: Optional[str] = None
    auto_select_topic: bool = True
    topic_left: Optional[str] = None
    topic_right: Optional[str] = None
    topic_angle: Optional[str] = None
    language: str = "en"
    niche: str = "food facts"


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    current_stage: str = ""
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_video_url: Optional[str] = None
    preview_url: Optional[str] = None
    caption: Optional[str] = None
    estimated_cost_usd: Optional[float] = None


class TopicIdeaRequest(BaseModel):
    niche: Optional[str] = None
    language: str = "en"
    count: int = 10
    blacklist: Optional[list[str]] = None


class TopicIdeaCandidate(BaseModel):
    title: str
    left: str
    right: str
    angle: str = ""
    why_it_might_work: str = ""
    risk_level: str = "low"


class TopicIdeaResponse(BaseModel):
    job_id: str
    status: str
    candidate: TopicIdeaCandidate
    total_in_history: int


class CreateTopicRequest(BaseModel):
    channel_id: Optional[str] = None
    left: str
    right: str
    angle: str = ""
    title: Optional[str] = None


class RenderRequest(BaseModel):
    spec_path: str
    output_dir: Optional[str] = None


class ApproveRequest(BaseModel):
    reason: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None
    regenerate: Optional[str] = None


class CostResponse(BaseModel):
    job_id: str
    total_cost_usd: float
    by_category: dict[str, float]


class PublicationPayload(BaseModel):
    platform: str
    video_url: str
    caption: str
    scheduled_at: Optional[str] = None
    privacy_level: str = "PUBLIC"
    disclose_ai_generated: bool = True
    disclose_branded_content: bool = False


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
    captured_at: str = ""
