from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class N8nWebhookService:
    def __init__(
        self,
        n8n_webhook_url: Optional[str] = None,
        internal_api_token: Optional[str] = None,
        notification_service: Optional[NotificationService] = None,
        timeout: float = 15.0,
    ):
        self.webhook_url = n8n_webhook_url
        self.internal_api_token = internal_api_token
        self.notification = notification_service
        self.timeout = timeout

    async def notify_completion(
        self,
        job_id: str,
        preview_url: str,
        video_url: str,
        caption: str,
        estimated_cost_usd: float,
        approve_url: str,
        reject_url: str,
        regenerate_url: Optional[str] = None,
    ) -> None:
        payload = {
            "job_id": job_id,
            "status": "WAITING_FOR_APPROVAL",
            "preview_url": preview_url,
            "video_url": video_url,
            "caption": caption,
            "estimated_cost_usd": round(estimated_cost_usd, 4),
            "approve_url": approve_url,
            "reject_url": reject_url,
        }
        if regenerate_url:
            payload["regenerate_url"] = regenerate_url

        if self.webhook_url:
            await self._call_webhook(payload)

        if self.notification:
            topic = payload.get("topic", job_id)
            await self.notification.send_approval_request(
                job_id=job_id,
                topic=topic,
                preview_url=preview_url,
                video_url=video_url,
                caption=caption,
                estimated_cost_usd=estimated_cost_usd,
                approve_url=approve_url,
                reject_url=reject_url,
                regenerate_url=regenerate_url,
            )

    async def notify_failure(
        self,
        job_id: str,
        error_message: str,
        stage: str = "",
    ) -> None:
        if self.notification:
            await self.notification.send_failure_alert(
                job_id=job_id,
                error_message=error_message,
                stage=stage,
            )

    async def notify_success(
        self,
        job_id: str,
        platforms: list[str],
        publication_ids: list[str],
    ) -> None:
        if self.notification:
            await self.notification.send_success_notification(
                job_id=job_id,
                platforms=platforms,
                publication_ids=publication_ids,
            )

    async def _call_webhook(self, payload: dict) -> None:
        if not self.webhook_url:
            return
        headers = {"Content-Type": "application/json"}
        if self.internal_api_token:
            headers["Authorization"] = f"Bearer {self.internal_api_token}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=payload, headers=headers)
            if resp.status_code in (200, 204):
                logger.info(f"n8n webhook called successfully: {self.webhook_url}")
            else:
                logger.warning(
                    f"n8n webhook failed: {resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"n8n webhook error: {e}")
