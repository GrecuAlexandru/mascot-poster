from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import or_, select

from app.automation.database import AutomationDatabase, AutomationJobRow
from app.automation.models import AutomationJob, JobState, RegenerationKind


class InvalidTransition(RuntimeError):
    pass


class JobNotFound(LookupError):
    pass


class JobService:
    def __init__(self, database: AutomationDatabase):
        self.database = database

    def create_job(
        self,
        target_at: datetime,
        topic_override: str | None = None,
        language: str = "ro",
        target_duration_seconds: int = 25,
        voice_id: str | None = None,
    ) -> AutomationJob:
        now = self._now()
        row = AutomationJobRow(
            id=str(uuid4()),
            state=JobState.QUEUED.value,
            created_at=now,
            updated_at=now,
            target_at=target_at,
            topic_override=topic_override,
            language=language,
            target_duration_seconds=target_duration_seconds,
            voice_id=voice_id,
            action_token=self._token(),
        )
        with self.database.session() as session:
            session.add(row)
        return self._snapshot(row)

    def get(self, job_id: str) -> AutomationJob:
        with self.database.session() as session:
            row = session.get(AutomationJobRow, job_id)
            if row is None:
                raise JobNotFound(job_id)
            return self._snapshot(row)

    def get_by_action_token(self, action_token: str) -> AutomationJob:
        with self.database.session() as session:
            row = session.scalar(
                select(AutomationJobRow).where(
                    AutomationJobRow.action_token == action_token
                )
            )
            if row is None:
                raise JobNotFound(action_token)
            return self._snapshot(row)

    def list_active(self, limit: int = 20) -> list[AutomationJob]:
        terminal = {
            JobState.PUBLISHED.value,
            JobState.REJECTED.value,
            JobState.MISSED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
        }
        with self.database.session() as session:
            rows = session.scalars(
                select(AutomationJobRow)
                .where(AutomationJobRow.state.not_in(terminal))
                .order_by(AutomationJobRow.target_at)
                .limit(limit)
            ).all()
            return [self._snapshot(row) for row in rows]

    def list_pending_reviews(self, limit: int = 10) -> list[AutomationJob]:
        with self.database.session() as session:
            rows = session.scalars(
                select(AutomationJobRow)
                .where(
                    AutomationJobRow.state == JobState.WAITING_FOR_APPROVAL.value,
                    AutomationJobRow.telegram_message_id.is_(None),
                )
                .order_by(AutomationJobRow.target_at)
                .limit(limit)
            ).all()
            return [self._snapshot(row) for row in rows]

    def record_telegram_message(
        self,
        job_id: str,
        chat_id: int,
        message_id: int,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.WAITING_FOR_APPROVAL)
            if row.telegram_message_id is not None:
                return self._snapshot(row)
            row.telegram_chat_id = chat_id
            row.telegram_message_id = message_id
            row.telegram_notified_at = self._now()
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def claim_next(self, worker_id: str, lease_seconds: int = 300) -> AutomationJob | None:
        now = self._now()
        with self.database.session() as session:
            statement = (
                select(AutomationJobRow)
                .where(
                    or_(
                        AutomationJobRow.state == JobState.QUEUED.value,
                        (
                            (AutomationJobRow.state == JobState.RUNNING.value)
                            & (AutomationJobRow.lease_expires_at < now)
                        ),
                    )
                )
                .order_by(AutomationJobRow.created_at)
                .limit(1)
            )
            if session.bind and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = session.scalar(statement)
            if row is None:
                return None
            row.state = JobState.RUNNING.value
            row.lease_owner = worker_id
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            self._touch(row, now)
            session.flush()
            return self._snapshot(row)

    def extend_lease(self, job_id: str, worker_id: str, lease_seconds: int = 300) -> None:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state != JobState.RUNNING.value or row.lease_owner != worker_id:
                raise InvalidTransition("worker does not own the running job")
            row.lease_expires_at = self._now() + timedelta(seconds=lease_seconds)
            self._touch(row)

    def complete_generation(
        self,
        job_id: str,
        video_path: Path,
        caption: str,
        topic: str,
    ) -> AutomationJob:
        if not video_path.is_file():
            raise FileNotFoundError(video_path)
        digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.RUNNING)
            row.state = JobState.WAITING_FOR_APPROVAL.value
            row.topic = topic
            row.caption = caption
            row.video_path = str(video_path)
            row.video_sha256 = digest
            row.regeneration_kind = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.action_token = self._token()
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def approve(
        self,
        job_id: str,
        expected_video_sha256: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        now: datetime | None = None,
    ) -> AutomationJob:
        now = now or self._now()
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state == JobState.APPROVED.value:
                if row.approved_video_sha256 == expected_video_sha256:
                    return self._snapshot(row)
                raise InvalidTransition("approval is bound to another video hash")
            self._require(row, JobState.WAITING_FOR_APPROVAL)
            if row.video_sha256 != expected_video_sha256:
                raise InvalidTransition("video hash does not match approval request")
            if self._as_utc(now) > self._as_utc(row.target_at) + timedelta(hours=3):
                row.state = JobState.MISSED.value
                row.local_delete_after = now + timedelta(days=7)
                row.telegram_user_id = telegram_user_id
                row.telegram_chat_id = telegram_chat_id
                self._touch(row, now)
                session.flush()
                return self._snapshot(row)
            row.state = JobState.APPROVED.value
            row.approval_id = str(uuid4())
            row.approved_video_sha256 = expected_video_sha256
            row.approved_at = now
            row.telegram_user_id = telegram_user_id
            row.telegram_chat_id = telegram_chat_id
            row.action_token = self._token()
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def reject(
        self,
        job_id: str,
        reason: str,
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.WAITING_FOR_APPROVAL)
            row.state = JobState.REJECTED.value
            row.rejection_reason = reason
            row.telegram_user_id = telegram_user_id
            row.telegram_chat_id = telegram_chat_id
            row.local_delete_after = self._now() + timedelta(days=7)
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def request_regeneration(
        self, job_id: str, kind: RegenerationKind
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state not in {
                JobState.WAITING_FOR_APPROVAL.value,
                JobState.APPROVED.value,
            }:
                raise InvalidTransition("job is not eligible for regeneration")
            row.state = JobState.QUEUED.value
            row.regeneration_kind = kind.value
            row.video_path = None
            row.video_sha256 = None
            row.approval_id = None
            row.approved_video_sha256 = None
            row.approved_at = None
            row.telegram_message_id = None
            row.telegram_notified_at = None
            row.action_token = self._token()
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def cancel(self, job_id: str) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state not in {
                JobState.QUEUED.value,
                JobState.RUNNING.value,
                JobState.WAITING_FOR_APPROVAL.value,
            }:
                raise InvalidTransition("job cannot be cancelled in its current state")
            row.state = JobState.CANCELLED.value
            row.local_delete_after = self._now() + timedelta(days=7)
            row.lease_owner = None
            row.lease_expires_at = None
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def mark_missed(self, job_id: str, now: datetime | None = None) -> AutomationJob:
        now = now or self._now()
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.WAITING_FOR_APPROVAL)
            if self._as_utc(now) <= self._as_utc(row.target_at) + timedelta(hours=3):
                raise InvalidTransition("approval window has not expired")
            row.state = JobState.MISSED.value
            row.local_delete_after = now + timedelta(days=7)
            self._touch(row, now)
            session.flush()
            return self._snapshot(row)

    def expire_overdue_approvals(
        self, now: datetime | None = None
    ) -> list[AutomationJob]:
        now = now or self._now()
        expired: list[AutomationJob] = []
        with self.database.session() as session:
            rows = session.scalars(
                select(AutomationJobRow).where(
                    AutomationJobRow.state == JobState.WAITING_FOR_APPROVAL.value
                )
            ).all()
            for row in rows:
                if self._as_utc(now) <= self._as_utc(row.target_at) + timedelta(hours=3):
                    continue
                row.state = JobState.MISSED.value
                row.local_delete_after = now + timedelta(days=7)
                self._touch(row, now)
                expired.append(self._snapshot(row))
            session.flush()
        return expired

    def begin_media_staging(self, job_id: str) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.APPROVED)
            if row.approved_video_sha256 != row.video_sha256:
                raise InvalidTransition("approved video hash no longer matches")
            row.state = JobState.STAGING_MEDIA.value
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def record_staged_media(
        self,
        job_id: str,
        object_key: str,
        public_url: str,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.STAGING_MEDIA)
            row.r2_object_key = object_key
            row.r2_public_url = public_url
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def record_buffer_post(
        self,
        job_id: str,
        post_id: str,
        buffer_status: str,
        now: datetime | None = None,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            self._require(row, JobState.STAGING_MEDIA)
            row.buffer_post_id = post_id
            row.buffer_status = buffer_status
            self._apply_buffer_status(row, buffer_status, now=now)
            self._touch(row, now)
            session.flush()
            return self._snapshot(row)

    def update_buffer_status(
        self,
        job_id: str,
        buffer_status: str,
        error_message: str | None = None,
        published_at: datetime | None = None,
        now: datetime | None = None,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state not in {
                JobState.SCHEDULED.value,
                JobState.PUBLISHING.value,
                JobState.PUBLISHED.value,
            }:
                raise InvalidTransition("job is not tracked by Buffer")
            row.buffer_status = buffer_status
            if error_message:
                row.error_message = error_message[:4000]
            self._apply_buffer_status(
                row,
                buffer_status,
                now=now,
                published_at=published_at,
            )
            self._touch(row, now)
            session.flush()
            return self._snapshot(row)

    def list_cleanup_due(
        self,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[AutomationJob]:
        now = now or self._now()
        with self.database.session() as session:
            rows = session.scalars(
                select(AutomationJobRow)
                .where(
                    or_(
                        (
                            AutomationJobRow.r2_object_key.is_not(None)
                            & (AutomationJobRow.r2_delete_after <= now)
                        ),
                        (
                            AutomationJobRow.video_path.is_not(None)
                            & (AutomationJobRow.local_delete_after <= now)
                        ),
                    )
                )
                .order_by(AutomationJobRow.updated_at)
                .limit(limit)
            ).all()
            return [self._snapshot(row) for row in rows]

    def record_cleanup(
        self,
        job_id: str,
        r2_deleted: bool,
        local_deleted: bool,
    ) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if r2_deleted:
                row.r2_object_key = None
                row.r2_public_url = None
                row.r2_delete_after = None
            if local_deleted:
                row.video_path = None
                row.local_delete_after = None
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    def fail(self, job_id: str, message: str) -> AutomationJob:
        with self.database.session() as session:
            row = self._row(session, job_id)
            if row.state in {JobState.PUBLISHED.value, JobState.CANCELLED.value}:
                raise InvalidTransition("terminal job cannot fail")
            row.state = JobState.FAILED.value
            row.error_message = message[:4000]
            row.local_delete_after = self._now() + timedelta(days=7)
            if row.r2_object_key:
                row.r2_delete_after = self._now() + timedelta(days=2)
            row.lease_owner = None
            row.lease_expires_at = None
            self._touch(row)
            session.flush()
            return self._snapshot(row)

    @staticmethod
    def _row(session, job_id: str) -> AutomationJobRow:
        row = session.get(AutomationJobRow, job_id)
        if row is None:
            raise JobNotFound(job_id)
        return row

    @staticmethod
    def _require(row: AutomationJobRow, expected: JobState) -> None:
        if row.state != expected.value:
            raise InvalidTransition(
                f"expected {expected.value}, found {row.state}"
            )

    @staticmethod
    def _touch(row: AutomationJobRow, now: datetime | None = None) -> None:
        row.updated_at = now or JobService._now()
        row.version += 1

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _apply_buffer_status(
        row: AutomationJobRow,
        buffer_status: str,
        now: datetime | None = None,
        published_at: datetime | None = None,
    ) -> None:
        now = now or JobService._now()
        if buffer_status == "sent":
            row.state = JobState.PUBLISHED.value
            row.published_at = published_at or now
            row.r2_delete_after = now + timedelta(hours=48)
            row.local_delete_after = now + timedelta(days=30)
        elif buffer_status == "sending":
            row.state = JobState.PUBLISHING.value
        elif buffer_status == "error":
            row.state = JobState.FAILED.value
            row.r2_delete_after = now + timedelta(days=2)
            row.local_delete_after = now + timedelta(days=7)
        else:
            row.state = JobState.SCHEDULED.value

    @staticmethod
    def _token() -> str:
        return uuid4().hex

    @staticmethod
    def _snapshot(row: AutomationJobRow) -> AutomationJob:
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        values.pop("version", None)
        for key, value in values.items():
            if isinstance(value, datetime) and value.tzinfo is None:
                values[key] = value.replace(tzinfo=timezone.utc)
        return AutomationJob.model_validate(values)
