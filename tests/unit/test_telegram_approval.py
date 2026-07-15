from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.automation.database import AutomationDatabase
from app.automation.job_service import JobService
from app.automation.models import JobState, RegenerationKind
from app.automation.telegram_bot import TelegramApprovalBot


class FakeTelegramClient:
    def __init__(self):
        self.videos = []
        self.messages = []
        self.callback_answers = []

    async def send_video(self, **kwargs):
        self.videos.append(kwargs)
        return 321

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return 654

    async def answer_callback(self, callback_query_id: str, text: str):
        self.callback_answers.append((callback_query_id, text))


def build_service(tmp_path: Path) -> JobService:
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    return JobService(database)


def ready_job(service: JobService, tmp_path: Path):
    job = service.create_job(
        target_at=datetime.now(timezone.utc) + timedelta(hours=2),
        topic_override="Cafea vs ceai",
    )
    service.claim_next("worker")
    video = tmp_path / f"{job.id}.mp4"
    video.write_bytes(b"video")
    return service.complete_generation(
        job.id,
        video,
        caption="Tu ce alegi?",
        topic="Cafea vs ceai",
    )


def callback_update(job, action: str, user_id: int = 7, chat_id: int = 8):
    return {
        "update_id": 99,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": user_id},
            "message": {"chat": {"id": chat_id}},
            "data": f"{action}:{job.action_token}",
        },
    }


def test_bot_sends_each_ready_video_once_with_hash_bound_buttons(tmp_path: Path):
    service = build_service(tmp_path)
    job = ready_job(service, tmp_path)
    client = FakeTelegramClient()
    bot = TelegramApprovalBot(service, client, allowed_user_id=7, review_chat_id=8)

    asyncio.run(bot.send_pending_reviews())
    asyncio.run(bot.send_pending_reviews())

    assert len(client.videos) == 1
    sent = client.videos[0]
    assert sent["chat_id"] == 8
    assert sent["video_path"] == job.video_path
    assert (job.video_sha256 or "")[:12] in sent["caption"]
    buttons = sent["reply_markup"]["inline_keyboard"]
    callback_data = [button["callback_data"] for row in buttons for button in row]
    assert f"approve:{job.action_token}" in callback_data
    stored = service.get(job.id)
    assert stored.telegram_message_id == 321


def test_authorized_approve_callback_approves_exact_video(tmp_path: Path):
    service = build_service(tmp_path)
    job = ready_job(service, tmp_path)
    client = FakeTelegramClient()
    bot = TelegramApprovalBot(service, client, allowed_user_id=7, review_chat_id=8)

    asyncio.run(bot.handle_update(callback_update(job, "approve")))

    assert service.get(job.id).state is JobState.APPROVED
    assert client.callback_answers == [("callback-1", "Aprobat pentru publicare.")]


def test_unauthorized_callback_cannot_change_state(tmp_path: Path):
    service = build_service(tmp_path)
    job = ready_job(service, tmp_path)
    client = FakeTelegramClient()
    bot = TelegramApprovalBot(service, client, allowed_user_id=7, review_chat_id=8)

    asyncio.run(bot.handle_update(callback_update(job, "approve", user_id=999)))

    assert service.get(job.id).state is JobState.WAITING_FOR_APPROVAL
    assert client.callback_answers == [("callback-1", "Neautorizat.")]


def test_regenerate_script_callback_invalidates_approval_and_requeues(tmp_path: Path):
    service = build_service(tmp_path)
    job = ready_job(service, tmp_path)
    client = FakeTelegramClient()
    bot = TelegramApprovalBot(service, client, allowed_user_id=7, review_chat_id=8)

    asyncio.run(bot.handle_update(callback_update(job, "regen_script")))

    stored = service.get(job.id)
    assert stored.state is JobState.QUEUED
    assert stored.regeneration_kind is RegenerationKind.SCRIPT
    assert stored.video_sha256 is None


def test_status_command_lists_active_jobs_only_for_owner(tmp_path: Path):
    service = build_service(tmp_path)
    job = ready_job(service, tmp_path)
    client = FakeTelegramClient()
    bot = TelegramApprovalBot(service, client, allowed_user_id=7, review_chat_id=8)
    update = {
        "update_id": 100,
        "message": {
            "from": {"id": 7},
            "chat": {"id": 8},
            "text": "/status",
        },
    }

    asyncio.run(bot.handle_update(update))

    assert len(client.messages) == 1
    assert job.id[:8] in client.messages[0]["text"]
    assert "WAITING_FOR_APPROVAL" in client.messages[0]["text"]
