from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.providers.search.base import ImageCandidate, SearchResponse, SearchResult
from app.services.job_cost_ledger import record_cost_event


class SearXNGError(Exception):
    pass


class SearXNGTransientError(SearXNGError):
    pass


class SearXNGProvider:
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def estimate_cost(self, num_queries: int) -> float:
        return 0.0

    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_images: bool = False,
    ) -> SearchResponse:
        general_task = self._fetch("general", query, max_results)
        if include_images:
            general, images = await asyncio.gather(
                general_task,
                self._fetch("images", query, max_results),
            )
        else:
            general = await general_task
            images = {"results": []}
        return SearchResponse(
            query=query,
            results=self._normalize_results(general),
            images=self._normalize_images(images),
            provider=self.name,
            estimated_cost_usd=0.0,
        )

    @retry(
        retry=retry_if_exception_type(SearXNGTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _fetch(
        self,
        category: str,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        operation = "image_search" if category == "images" else "web_search"
        try:
            payload = await self._get_json({
                "q": query,
                "format": "json",
                "categories": category,
                "pageno": 1,
                "language": "all",
            })
        except Exception as error:
            transient = isinstance(error, (httpx.HTTPError, SearXNGTransientError))
            record_cost_event(
                provider=self.name,
                operation=operation,
                input_units=1,
                unit_type="requests",
                amount_usd=0.0,
                pricing_source="self_hosted_no_query_fee",
                status="failed",
                error=f"{type(error).__name__}: {error}",
                request_key=f"{category}:{query}",
            )
            if transient:
                raise SearXNGTransientError(str(error)) from error
            raise SearXNGError(str(error)) from error
        if not isinstance(payload.get("results", []), list):
            raise SearXNGError("SearXNG JSON response does not contain a results list")
        record_cost_event(
            provider=self.name,
            operation=operation,
            input_units=1,
            unit_type="requests",
            amount_usd=0.0,
            pricing_source="self_hosted_no_query_fee",
            request_key=f"{category}:{query}",
        )
        return payload

    async def _get_json(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/search", params=params)
        except httpx.HTTPError:
            raise
        if response.status_code == 429 or response.status_code >= 500:
            raise SearXNGTransientError(f"SearXNG HTTP {response.status_code}")
        if response.status_code != 200:
            raise SearXNGError(f"SearXNG HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as error:
            raise SearXNGError("SearXNG did not return JSON; enable json format") from error
        if not isinstance(payload, dict):
            raise SearXNGError("SearXNG JSON response is not an object")
        return payload

    @staticmethod
    def _normalize_results(payload: dict[str, Any]) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for row in payload.get("results", []):
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            if not isinstance(url, str) or not url or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(
                title=row.get("title", ""),
                url=url,
                snippet=row.get("content", ""),
                score=SearXNGProvider._score(row.get("score")),
            ))
        return results

    @staticmethod
    def _normalize_images(payload: dict[str, Any]) -> list[ImageCandidate]:
        images: list[ImageCandidate] = []
        seen: set[str] = set()
        for row in payload.get("results", []):
            if not isinstance(row, dict):
                continue
            image_url = (
                row.get("img_src")
                or row.get("thumbnail_src")
                or row.get("image")
                or row.get("url")
            )
            if not isinstance(image_url, str) or not image_url or image_url in seen:
                continue
            seen.add(image_url)
            source_url = row.get("source") or row.get("url")
            images.append(ImageCandidate(
                url=image_url,
                description=row.get("content", ""),
                source_url=source_url if isinstance(source_url, str) and source_url else None,
                source_title=row.get("title", ""),
                score=SearXNGProvider._score(row.get("score")),
            ))
        return images

    @staticmethod
    def _score(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
