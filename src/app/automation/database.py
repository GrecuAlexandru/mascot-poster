from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AutomationJobRow(Base):
    __tablename__ = "automation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    topic_override: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="ro")
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=25)
    voice_id: Mapped[Optional[str]] = mapped_column(String(255))
    regeneration_kind: Mapped[Optional[str]] = mapped_column(String(16))
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128))
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    topic: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    video_path: Mapped[Optional[str]] = mapped_column(Text)
    video_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    approval_id: Mapped[Optional[str]] = mapped_column(String(36))
    approved_video_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    telegram_user_id: Mapped[Optional[int]] = mapped_column()
    telegram_chat_id: Mapped[Optional[int]] = mapped_column()
    telegram_message_id: Mapped[Optional[int]] = mapped_column()
    telegram_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    action_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    r2_object_key: Mapped[Optional[str]] = mapped_column(Text)
    r2_public_url: Mapped[Optional[str]] = mapped_column(Text)
    buffer_post_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    buffer_status: Mapped[Optional[str]] = mapped_column(String(64))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    r2_delete_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    local_delete_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AutomationDatabase:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
