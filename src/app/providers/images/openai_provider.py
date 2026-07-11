from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.images.base import GeneratedImage

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_IMAGE_COST = 0.04


class OpenAIImageError(Exception):
    pass


class OpenAIImageTransientError(OpenAIImageError):
    pass


class OpenAIImageProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-image-1-mini",
        timeout: float = 120.0,
        cache_dir: Optional[Any] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._cache_dir = cache_dir
        if cache_dir:
            from pathlib import Path
            Path(cache_dir).mkdir(parents=True, exist_ok=True)

    def estimate_cost(self, count: int = 1) -> float:
        return round(count * OPENAI_IMAGE_COST, 4)

    def _cache_key(self, prompt: str, width: int, height: int) -> str:
        parts = f"{prompt}|{width}x{height}|{self._model}"
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Optional[Any]:
        if not self._cache_dir:
            return None
        from pathlib import Path
        p = Path(self._cache_dir) / f"{key}.png"
        return p if p.exists() else None

    def _build_generation_body(
        self,
        prompt: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": self._resolve_size(width, height),
        }
        if self._model.startswith("gpt-image"):
            body.update({
                "background": "transparent",
                "output_format": "png",
                "quality": "medium",
            })
        else:
            body["response_format"] = "b64_json"
        return body

    @retry(
        retry=retry_if_exception_type(OpenAIImageTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        output_path: Any,
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedImage:
        from pathlib import Path
        output_path = Path(output_path)

        key = self._cache_key(prompt, width, height)
        cached = self._cache_path(key)
        if cached:
            logger.info(f"Image cache hit: {key[:12]}...")
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
        body = self._build_generation_body(prompt, width, height)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{OPENAI_BASE_URL}/images/generations",
                headers=headers,
                json=body,
            )

        if response.status_code == 429:
            raise OpenAIImageTransientError("Rate limited")
        if response.status_code >= 500:
            raise OpenAIImageTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            raise OpenAIImageError(
                f"OpenAI image API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        image_data = base64.b64decode(data["data"][0]["b64_json"])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_data)

        if self._cache_dir:
            from pathlib import Path as P
            cache_file = P(self._cache_dir) / f"{key}.png"
            cache_file.write_bytes(image_data)

        cost = self.estimate_cost(1)
        logger.info(f"Image generated: {output_path.name}, ~${cost:.4f}")

        return GeneratedImage(
            path=output_path,
            prompt=prompt,
            width=width,
            height=height,
            provider=self.name,
            estimated_cost_usd=cost,
        )

    def _resolve_size(self, width: int, height: int) -> str:
        if self._model.startswith("gpt-image"):
            if width == height:
                return "1024x1024"
            if width > height:
                return "1536x1024"
            return "1024x1536"
        if width == height:
            if width == 1024:
                return "1024x1024"
            if width == 1792:
                return "1792x1024"
        if width > height:
            return "1792x1024"
        return "1024x1792"


class RemoteImageProvider:
    name = "remote"

    def __init__(self, timeout: float = 30.0, cache_dir: Optional[Any] = None):
        self._timeout = timeout
        self._cache_dir = cache_dir
        if cache_dir:
            from pathlib import Path
            Path(cache_dir).mkdir(parents=True, exist_ok=True)

    def estimate_cost(self, count: int = 1) -> float:
        return 0.0

    @retry(
        retry=retry_if_exception_type(OpenAIImageTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def download(
        self,
        url: str,
        output_path: Any,
    ) -> GeneratedImage:
        from pathlib import Path
        output_path = Path(output_path)

        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        if self._cache_dir:
            cached = Path(self._cache_dir) / f"{key}.png"
            if cached.exists():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(cached.read_bytes())
                return GeneratedImage(
                    path=output_path,
                    prompt=url,
                    provider=self.name,
                    cached=True,
                )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, follow_redirects=True)

        if response.status_code >= 500:
            raise OpenAIImageTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            raise OpenAIImageError(f"Download failed {response.status_code}: {url[:200]}")

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise OpenAIImageError(f"Not an image (content-type={content_type}): {url[:200]}")

        image_data = response.content
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_data)

        if self._cache_dir:
            from pathlib import Path as P
            cached = P(self._cache_dir) / f"{key}.png"
            cached.write_bytes(image_data)

        logger.info(f"Image downloaded: {url[:80]} → {output_path.name}")
        return GeneratedImage(
            path=output_path,
            prompt=url,
            provider=self.name,
        )
