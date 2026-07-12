from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image, UnidentifiedImageError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.images.base import GeneratedImage
from app.providers.images.openai_provider import OpenAIImageError, OpenAIImageTransientError
from app.services.job_cost_ledger import record_cost_event

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

    def _cache_key(
        self,
        prompt: str,
        width: int,
        height: int,
        input_references: Optional[list[Path]] = None,
    ) -> str:
        reference_hashes = [
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in input_references or []
        ]
        value = f"{prompt}|{width}x{height}|{self._model}|{'|'.join(reference_hashes)}"
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
        input_references: Optional[list[Path]] = None,
    ) -> dict[str, Any]:
        if self._model.startswith("google/gemini-"):
            body: dict[str, Any] = {
                "model": self._model,
                "prompt": prompt,
                "n": 1,
                "resolution": "1K",
                "aspect_ratio": self._resolve_aspect_ratio(width, height),
            }
        else:
            body = {
                "model": self._model,
                "prompt": prompt,
                "n": 1,
                "size": self._resolve_size(width, height),
                "background": "transparent",
                "output_format": "png",
                "quality": "medium",
            }
        if input_references:
            body["input_references"] = [
                self._encode_reference(path)
                for path in input_references
            ]
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
        output_path: Path,
        width: int = 1024,
        height: int = 1024,
        input_references: Optional[list[Path]] = None,
    ) -> GeneratedImage:
        output_path = Path(output_path)
        key = self._cache_key(prompt, width, height, input_references)
        cached = self._cache_path(key)
        if cached:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(cached.read_bytes())
            self._normalize_to_png(output_path.read_bytes(), output_path)
            record_cost_event(
                provider=self.name,
                model=self._model,
                operation="image_generation",
                unit_type="images",
                amount_usd=0.0,
                pricing_source="cache_hit",
                cached=True,
                request_key=key,
            )
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
                json=self._build_generation_body(
                    prompt,
                    width,
                    height,
                    input_references,
                ),
            )
        if response.status_code == 429:
            record_cost_event(provider=self.name, model=self._model, operation="image_generation", status="failed", pricing_source="request_failed", error="HTTP 429", request_key=key)
            raise OpenAIImageTransientError("OpenRouter image request was rate limited")
        if response.status_code >= 500:
            record_cost_event(provider=self.name, model=self._model, operation="image_generation", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=key)
            raise OpenAIImageTransientError(
                f"OpenRouter image server error: {response.status_code}"
            )
        if response.status_code != 200:
            record_cost_event(provider=self.name, model=self._model, operation="image_generation", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=key)
            raise OpenAIImageError(
                f"OpenRouter image API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        try:
            image_data = base64.b64decode(data["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise OpenAIImageError("OpenRouter image response did not contain PNG data") from error
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._normalize_to_png(image_data, output_path)
        if self._cache_dir:
            (self._cache_dir / f"{key}.png").write_bytes(output_path.read_bytes())
        reported_cost = data.get("usage", {}).get("cost")
        cost = float(reported_cost if reported_cost is not None else self.estimate_cost(1))
        record_cost_event(
            provider=self.name,
            model=self._model,
            operation="image_generation",
            input_units=1,
            unit_type="images",
            amount_usd=cost,
            amount_kind="actual" if reported_cost is not None else "estimated",
            pricing_source="provider_usage" if reported_cost is not None else "configured_image_rate",
            request_key=key,
        )
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

    @staticmethod
    def _resolve_aspect_ratio(width: int, height: int) -> str:
        if width == height:
            return "1:1"
        return "3:2" if width > height else "2:3"

    @staticmethod
    def _normalize_to_png(image_data: bytes, output_path: Path) -> None:
        try:
            with Image.open(BytesIO(image_data)) as source:
                image = source.convert("RGBA")
            image.save(output_path, format="PNG")
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise OpenAIImageError("OpenRouter image response contained invalid image data") from error

    @staticmethod
    def _encode_reference(path: Path) -> dict[str, Any]:
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        }
