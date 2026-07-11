from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        discord_webhook_url: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.discord_webhook_url = discord_webhook_url
        self.slack_webhook_url = slack_webhook_url
        self.timeout = timeout

    async def send_approval_request(
        self,
        job_id: str,
        topic: str,
        preview_url: str,
        video_url: str,
        caption: str,
        estimated_cost_usd: float,
        approve_url: str,
        reject_url: str,
        regenerate_url: Optional[str] = None,
    ) -> None:
        message = self._format_approval_message(
            job_id=job_id,
            topic=topic,
            preview_url=preview_url,
            video_url=video_url,
            caption=caption,
            cost=estimated_cost_usd,
            approve_url=approve_url,
            reject_url=reject_url,
            regenerate_url=regenerate_url,
        )

        await self._send_all(message)

    async def send_failure_alert(
        self,
        job_id: str,
        error_message: str,
        stage: str = "",
    ) -> None:
        message = (
            f"ALERT: Job {job_id} FAILED\n"
            f"Stage: {stage}\n"
            f"Error: {error_message}\n"
            f"Time: {self._timestamp()}"
        )
        await self._send_all(message)

    async def send_success_notification(
        self,
        job_id: str,
        platforms: list[str],
        publication_ids: list[str],
    ) -> None:
        platforms_str = ", ".join(platforms)
        ids_str = "\n".join(publication_ids)
        message = (
            f"SUCCESS: Job {job_id} published\n"
            f"Platforms: {platforms_str}\n"
            f"Publication IDs:\n{ids_str}\n"
            f"Time: {self._timestamp()}"
        )
        await self._send_all(message)

    async def send_daily_summary(
        self,
        total_jobs: int,
        successful: int,
        failed: int,
        total_cost: float,
    ) -> None:
        message = (
            f"Daily Summary\n"
            f"Total jobs: {total_jobs}\n"
            f"Successful: {successful}\n"
            f"Failed: {failed}\n"
            f"Total cost: ${total_cost:.4f}\n"
            f"Time: {self._timestamp()}"
        )
        await self._send_all(message)

    async def _send_all(self, message: str) -> None:
        if self.telegram_bot_token and self.telegram_chat_id:
            await self._send_telegram(message)
        if self.discord_webhook_url:
            await self._send_discord(message)
        if self.slack_webhook_url:
            await self._send_slack(message)

    async def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram notification sent")
            else:
                logger.warning(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Telegram notification error: {e}")

    async def _send_discord(self, message: str) -> None:
        payload = {"content": message[:2000]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.discord_webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("Discord notification sent")
            else:
                logger.warning(f"Discord send failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Discord notification error: {e}")

    async def _send_slack(self, message: str) -> None:
        payload = {"text": message[:3000]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.slack_webhook_url, json=payload)
            if resp.status_code == 200:
                logger.info("Slack notification sent")
            else:
                logger.warning(f"Slack send failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Slack notification error: {e}")

    @staticmethod
    def _format_approval_message(
        job_id: str,
        topic: str,
        preview_url: str,
        video_url: str,
        caption: str,
        cost: float,
        approve_url: str,
        reject_url: str,
        regenerate_url: Optional[str],
    ) -> str:
        lines = [
            f"VIDEO READY FOR APPROVAL",
            f"Job: {job_id}",
            f"Topic: {topic}",
            f"Cost: ${cost:.4f}",
            f"",
            f"Caption: {caption}",
            f"",
            f"Preview: {preview_url}",
            f"Video: {video_url}",
            f"",
            f"Approve: {approve_url}",
            f"Reject: {reject_url}",
        ]
        if regenerate_url:
            lines.append(f"Regenerate: {regenerate_url}")
        return "\n".join(lines)

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
