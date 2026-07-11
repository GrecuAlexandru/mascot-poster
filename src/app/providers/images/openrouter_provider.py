from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.images.base import GeneratedImage
from app.providers.images.openai_provider import OpenAIImageError, OpenAIImageTransientError

logger = logging.getLogger(__name__)

OPENROUTER_IMAGE_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_IMAGE_COST = 0.04


class OpenRouterImageProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-image-1-mini",
        timeout: float = 120.0,
        cache_dir: Optional[Any] = None,
        base_url: str = OPENROUTER_IMAGE_BASE_URL,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._base_url = base_url.rstrip("/")
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/images"

    def estimate_cost(self, count: int = 1) -> float:
        return round(count * OPENROUTER_IMAGE_COST, 4)

    def _cache_key(self, prompt: str, width: int, height: int) -> str:
        value = f"{prompt}|{width}x{height}|{self._model}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Optional[Path]:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"{key}.png"
        return path if path.exists() else None

    def _build_generation_body(
        self,
        prompt: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": self._resolve_size(width, height),
            "background": "transparent",
            "output_format": "png",
            "quality": "medium",
        }

    @retry(
        retry=retry_if_exception_type(OpenAIImageTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedImage:
        output_path = Path(output_path)
        key = self._cache_key(prompt, width, height)
        cached = self._cache_path(key)
        if cached:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(cached.read_bytes())
            return GeneratedImage(
                path=output_path,
                prompt=prompt,
                width=width,
                height=height,
                provider=self.name,
                cached=True,
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json=self._build_generation_body(prompt, width, height),
            )
        if response.status_code == 429:
            raise OpenAIImageTransientError("OpenRouter image request was rate limited")
        if response.status_code >= 500:
            raise OpenAIImageTransientError(
                f"OpenRouter image server error: {response.status_code}"
            )
        if response.status_code != 200:
            raise OpenAIImageError(
                f"OpenRouter image API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        try:
            image_data = base64.b64decode(data["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise OpenAIImageError("OpenRouter image response did not contain PNG data") from error
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_data)
        if self._cache_dir:
            (self._cache_dir / f"{key}.png").write_bytes(image_data)
        cost = float(data.get("usage", {}).get("cost", self.estimate_cost(1)))
        logger.info("OpenRouter image generated: %s, ~$%.4f", output_path.name, cost)
        return GeneratedImage(
            path=output_path,
            prompt=prompt,
            width=width,
            height=height,
            provider=self.name,
            estimated_cost_usd=cost,
        )

    @staticmethod
    def _resolve_size(width: int, height: int) -> str:
        if width == height:
            return "1024x1024"
        if width > height:
            return "1536x1024"
        return "1024x1536"
