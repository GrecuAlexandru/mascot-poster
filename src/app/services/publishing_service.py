from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from typing import Literal

logger = logging.getLogger(__name__)


class PublicationPayload(BaseModel):
    platform: str
    video_url: str
    caption: str
    scheduled_at: Optional[str] = None
    privacy_level: str = "PUBLIC"
    disclose_ai_generated: bool = True
    disclose_branded_content: bool = False


class PublicationResult(BaseModel):
    platform: str
    publication_id: str
    status: str = "published"
    url: str = ""
    posted_at: str = ""
    error: Optional[str] = None


class TikTokPublisher:
    name = "tiktok"

    def __init__(self, access_token: Optional[str] = None, timeout: float = 30.0):
        self._access_token = access_token
        self._timeout = timeout

    async def publish(self, payload: PublicationPayload) -> PublicationResult:
        if not self._access_token:
            return PublicationResult(
                platform=self.name,
                publication_id="",
                status="skipped",
                error="No TikTok access token configured",
            )

        import httpx

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "video_url": payload.video_url,
            "caption": payload.caption[:2200],
            "privacy_level": payload.privacy_level,
            "is_ai_generated": payload.disclose_ai_generated,
            "is_branded_content": payload.disclose_branded_content,
        }
        if payload.scheduled_at:
            body["scheduled_publish_time"] = payload.scheduled_at

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    "https://open.tiktokapis.com/v2/post/publish/video/init/",
                    headers=headers,
                    json=body,
                )

            if resp.status_code == 200:
                data = resp.json()
                pub_id = data.get("publish_id", "")
                logger.info(f"TikTok published: {pub_id}")
                return PublicationResult(
                    platform=self.name,
                    publication_id=pub_id,
                    status="published",
                    posted_at=datetime.now(timezone.utc).isoformat(),
                )
            return PublicationResult(
                platform=self.name,
                publication_id="",
                status="failed",
                error=f"TikTok API {resp.status_code}: {resp.text[:200]}",
            )
        except Exception as e:
            return PublicationResult(
                platform=self.name,
                publication_id="",
                status="failed",
                error=str(e),
            )


class YouTubePublisher:
    name = "youtube"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    async def publish(self, payload: PublicationPayload) -> PublicationResult:
        return PublicationResult(
            platform=self.name,
            publication_id="",
            status="not_implemented",
            error="YouTube Shorts publishing not yet implemented",
        )


class InstagramPublisher:
    name = "instagram"

    def __init__(self, access_token: Optional[str] = None, timeout: float = 30.0):
        self._access_token = access_token
        self._timeout = timeout

    async def publish(self, payload: PublicationPayload) -> PublicationResult:
        return PublicationResult(
            platform=self.name,
            publication_id="",
            status="not_implemented",
            error="Instagram Reels publishing not yet implemented",
        )


class PublishingService:
    def __init__(
        self,
        tiktok_publisher: Optional[TikTokPublisher] = None,
        youtube_publisher: Optional[YouTubePublisher] = None,
        instagram_publisher: Optional[InstagramPublisher] = None,
    ):
        self.tiktok = tiktok_publisher
        self.youtube = youtube_publisher
        self.instagram = instagram_publisher

    async def publish_to_all(self, payload: PublicationPayload) -> list[PublicationResult]:
        results: list[PublicationResult] = []

        if self.tiktok:
            results.append(await self.tiktok.publish(payload))
        if self.youtube:
            youtube_payload = payload.model_copy(update={"platform": "youtube"})
            results.append(await self.youtube.publish(youtube_payload))
        if self.instagram:
            ig_payload = payload.model_copy(update={"platform": "instagram"})
            results.append(await self.instagram.publish(ig_payload))

        successful = sum(1 for r in results if r.status == "published")
        logger.info(
            f"Publishing complete: {successful}/{len(results)} platforms succeeded"
        )
        return results

    async def publish_to_platform(self, platform: str, payload: PublicationPayload) -> PublicationResult:
        if platform == "tiktok" and self.tiktok:
            return await self.tiktok.publish(payload)
        if platform == "youtube" and self.youtube:
            return await self.youtube.publish(payload)
        if platform == "instagram" and self.instagram:
            return await self.instagram.publish(payload)
        return PublicationResult(
            platform=platform,
            publication_id="",
            status="skipped",
            error=f"Publisher for {platform} not configured",
        )
