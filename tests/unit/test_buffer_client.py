from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.automation.buffer_client import BufferClient


def test_buffer_client_uses_official_video_and_tiktok_metadata_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "createPost": {
                        "__typename": "PostActionSuccess",
                        "post": {
                            "id": "post-1",
                            "status": "scheduled",
                            "sentAt": None,
                        },
                    }
                }
            },
        )

    client = BufferClient("secret")
    asyncio.run(client.client.aclose())
    client.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.buffer.com"
    )
    due_at = datetime(2026, 7, 16, 6, tzinfo=timezone.utc)

    post = asyncio.run(
        client.create_video_post(
            channel_id="channel-1",
            text="Caption",
            video_url="https://media.example/video.mp4",
            mode="customScheduled",
            due_at=due_at,
            is_ai_generated=True,
        )
    )
    asyncio.run(client.close())

    input_payload = captured["variables"]["input"]
    assert post.id == "post-1"
    assert input_payload["schedulingType"] == "automatic"
    assert input_payload["mode"] == "customScheduled"
    assert input_payload["dueAt"] == "2026-07-16T06:00:00Z"
    assert input_payload["assets"][0]["video"]["url"].endswith("video.mp4")
    assert input_payload["metadata"]["tiktok"]["isAiGenerated"] is True
    assert input_payload["aiAssisted"] is True
