from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AutomationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTOMATION_",
        env_file=None,
        extra="ignore",
    )

    database_url: str = "sqlite:///output/automation.db"
    internal_api_token: Optional[SecretStr] = None
    telegram_bot_token: Optional[SecretStr] = None
    telegram_allowed_user_id: Optional[int] = None
    telegram_review_chat_id: Optional[int] = None
    telegram_poll_seconds: float = Field(default=2.0, gt=0)
    worker_id: str = "mascot-worker-1"
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    worker_lease_seconds: int = Field(default=300, ge=30)
    timezone: str = "Europe/Bucharest"
    r2_endpoint_url: Optional[str] = None
    r2_access_key_id: Optional[SecretStr] = None
    r2_secret_access_key: Optional[SecretStr] = None
    r2_bucket: Optional[str] = None
    r2_public_base_url: Optional[str] = None
    r2_object_prefix: str = "buffer"
    buffer_api_token: Optional[SecretStr] = None
    buffer_tiktok_channel_id: Optional[str] = None
    buffer_thumbnail_offset_ms: int = Field(default=2000, ge=0)
    cleanup_poll_seconds: float = Field(default=3600.0, gt=0)


@lru_cache
def get_automation_settings() -> AutomationSettings:
    return AutomationSettings()
