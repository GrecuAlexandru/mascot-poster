from __future__ import annotations

from datetime import datetime, timezone

import httpx
from pydantic import BaseModel


class BufferPost(BaseModel):
    id: str
    status: str
    sent_at: datetime | None = None
    error: str | None = None


class BufferClient:
    CREATE_VIDEO_POST = """
    mutation CreateVideoPost($input: CreatePostInput!) {
      createPost(input: $input) {
        __typename
        ... on PostActionSuccess {
          post { id status sentAt }
        }
        ... on MutationError { message }
      }
    }
    """
    GET_POST = """
    query GetPost($input: PostInput!) {
      post(input: $input) {
        id
        status
        sentAt
        error { message }
      }
    }
    """

    def __init__(
        self,
        api_token: str,
        endpoint: str = "https://api.buffer.com",
        timeout_seconds: float = 30.0,
    ):
        self.client = httpx.AsyncClient(
            base_url=endpoint,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def create_video_post(
        self,
        channel_id: str,
        text: str,
        video_url: str,
        mode: str,
        due_at: datetime | None,
        is_ai_generated: bool,
        thumbnail_offset_ms: int = 2000,
    ) -> BufferPost:
        input_payload = {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": mode,
            "assets": [
                {
                    "video": {
                        "url": video_url,
                        "metadata": {"thumbnailOffset": thumbnail_offset_ms},
                    }
                }
            ],
            "metadata": {"tiktok": {"isAiGenerated": is_ai_generated}},
            "aiAssisted": is_ai_generated,
            "source": "mascot-poster",
        }
        if due_at is not None:
            input_payload["dueAt"] = self._iso(due_at)
        payload = await self._graphql(
            self.CREATE_VIDEO_POST,
            {"input": input_payload},
        )
        result = payload.get("createPost", {})
        if result.get("__typename") != "PostActionSuccess":
            raise RuntimeError(str(result.get("message") or "Buffer rejected the post"))
        return self._post(result["post"])

    async def get_post(self, post_id: str) -> BufferPost:
        payload = await self._graphql(self.GET_POST, {"input": {"id": post_id}})
        return self._post(payload["post"])

    async def _graphql(self, query: str, variables: dict) -> dict:
        response = await self.client.post("", json={"query": query, "variables": variables})
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(str(errors[0].get("message") or "Buffer GraphQL error"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Buffer returned no data")
        return data

    @staticmethod
    def _post(payload: dict) -> BufferPost:
        error = payload.get("error")
        return BufferPost(
            id=str(payload["id"]),
            status=str(payload["status"]),
            sent_at=payload.get("sentAt"),
            error=error.get("message") if isinstance(error, dict) else None,
        )

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
