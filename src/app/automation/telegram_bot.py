from __future__ import annotations

import asyncio
from datetime import timezone
from typing import Any

from app.automation.job_service import InvalidTransition, JobNotFound, JobService
from app.automation.models import JobState, RegenerationKind


class TelegramApprovalBot:
    def __init__(
        self,
        job_service: JobService,
        client: Any,
        allowed_user_id: int,
        review_chat_id: int,
    ):
        self.job_service = job_service
        self.client = client
        self.allowed_user_id = allowed_user_id
        self.review_chat_id = review_chat_id
        self.update_offset: int | None = None

    async def send_pending_reviews(self) -> None:
        self.job_service.expire_overdue_approvals()
        for job in self.job_service.list_pending_reviews():
            if job.video_path is None or job.video_sha256 is None:
                continue
            message_id = await self.client.send_video(
                chat_id=self.review_chat_id,
                video_path=job.video_path,
                caption=self._review_caption(job),
                reply_markup=self._keyboard(job.action_token or ""),
            )
            self.job_service.record_telegram_message(
                job.id,
                chat_id=self.review_chat_id,
                message_id=message_id,
            )

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            await self._handle_callback(callback)
            return
        message = update.get("message")
        if isinstance(message, dict):
            await self._handle_message(message)

    async def run_forever(self, poll_seconds: float = 2.0) -> None:
        while True:
            await self.send_pending_reviews()
            updates = await self.client.get_updates(self.update_offset)
            for update in updates:
                update_id = int(update.get("update_id", 0))
                self.update_offset = max(self.update_offset or 0, update_id + 1)
                await self.handle_update(update)
            if not updates:
                await asyncio.sleep(poll_seconds)

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id", ""))
        user_id = int(callback.get("from", {}).get("id", 0))
        chat_id = int(callback.get("message", {}).get("chat", {}).get("id", 0))
        if not self._authorized(user_id, chat_id):
            await self.client.answer_callback(callback_id, "Neautorizat.")
            return
        data = str(callback.get("data", ""))
        action, separator, token = data.partition(":")
        if not separator or not token:
            await self.client.answer_callback(callback_id, "Comandă invalidă.")
            return
        try:
            job = self.job_service.get_by_action_token(token)
            if action == "approve":
                result = self.job_service.approve(
                    job.id,
                    job.video_sha256 or "",
                    telegram_user_id=user_id,
                    telegram_chat_id=chat_id,
                )
                text = (
                    "Aprobat pentru publicare."
                    if result.state is JobState.APPROVED
                    else "Fereastra de aprobare a expirat; jobul este MISSED."
                )
            elif action == "reject":
                self.job_service.reject(
                    job.id,
                    "Rejected in Telegram",
                    telegram_user_id=user_id,
                    telegram_chat_id=chat_id,
                )
                text = "Respins."
            elif action in {"regen_script", "regen_images", "regen_full"}:
                kind = {
                    "regen_script": RegenerationKind.SCRIPT,
                    "regen_images": RegenerationKind.IMAGES,
                    "regen_full": RegenerationKind.FULL,
                }[action]
                self.job_service.request_regeneration(job.id, kind)
                text = "Regenerare pusă în coadă."
            elif action == "cancel":
                self.job_service.cancel(job.id)
                text = "Anulat."
            else:
                text = "Comandă necunoscută."
        except (JobNotFound, InvalidTransition):
            text = "Acțiunea a expirat sau jobul s-a schimbat."
        await self.client.answer_callback(callback_id, text)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        user_id = int(message.get("from", {}).get("id", 0))
        chat_id = int(message.get("chat", {}).get("id", 0))
        if not self._authorized(user_id, chat_id):
            return
        command = str(message.get("text", "")).split()[0].split("@")[0]
        if command == "/status":
            jobs = self.job_service.list_active()
            if not jobs:
                text = "Nu există joburi active."
            else:
                text = "\n".join(
                    f"{job.id[:8]} · {job.state.value} · {job.target_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC"
                    for job in jobs
                )
        else:
            text = "Comenzi: /status, /help. Folosește butoanele de sub video pentru decizie."
        await self.client.send_message(chat_id=chat_id, text=text)

    def _authorized(self, user_id: int, chat_id: int) -> bool:
        return user_id == self.allowed_user_id and chat_id == self.review_chat_id

    @staticmethod
    def _keyboard(action_token: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ Aproba", "callback_data": f"approve:{action_token}"},
                    {"text": "❌ Respinge", "callback_data": f"reject:{action_token}"},
                ],
                [
                    {"text": "✍️ Script nou", "callback_data": f"regen_script:{action_token}"},
                    {"text": "🖼 Imagini noi", "callback_data": f"regen_images:{action_token}"},
                ],
                [
                    {"text": "🔄 Totul nou", "callback_data": f"regen_full:{action_token}"},
                    {"text": "🛑 Anulează", "callback_data": f"cancel:{action_token}"},
                ],
            ]
        }

    @staticmethod
    def _review_caption(job) -> str:
        return (
            f"{job.topic or 'Video nou'}\n\n"
            f"{job.caption or ''}\n\n"
            f"Țintă: {job.target_at:%Y-%m-%d %H:%M %Z}\n"
            f"Hash: {(job.video_sha256 or '')[:12]}"
        )
