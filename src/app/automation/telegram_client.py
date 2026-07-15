from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


class TelegramClient:
    def __init__(self, bot_token: str, timeout_seconds: float = 65.0):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 50,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self._post("getUpdates", json_payload=payload)
        return result if isinstance(result, list) else []

    async def send_video(
        self,
        chat_id: int,
        video_path: Path,
        caption: str,
        reply_markup: dict[str, Any],
    ) -> int:
        with Path(video_path).open("rb") as video:
            result = await self._post(
                "sendVideo",
                data={
                    "chat_id": str(chat_id),
                    "caption": caption,
                    "supports_streaming": "true",
                    "reply_markup": json.dumps(reply_markup),
                },
                files={"video": (Path(video_path).name, video, "video/mp4")},
            )
        return int(result["message_id"])

    async def send_message(self, chat_id: int, text: str) -> int:
        result = await self._post(
            "sendMessage",
            json_payload={"chat_id": chat_id, "text": text},
        )
        return int(result["message_id"])

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self._post(
            "answerCallbackQuery",
            json_payload={"callback_query_id": callback_query_id, "text": text},
        )

    async def _post(
        self,
        method: str,
        json_payload: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.client.post(
            f"{self.base_url}/{method}",
            json=json_payload,
            data=data,
            files=files,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram request failed for {method}")
        return payload.get("result")
