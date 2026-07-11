from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.search.base import ImageCandidate, SearchProvider, SearchResponse, SearchResult
from app.services.job_cost_ledger import record_cost_event

logger = logging.getLogger(__name__)

TAVILY_BASE_URL = "https://api.tavily.com"
TAVILY_COST_PER_QUERY = 0.01


class TavilyError(Exception):
    pass


class TavilyTransientError(TavilyError):
    pass


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def estimate_cost(self, num_queries: int) -> float:
        return round(num_queries * TAVILY_COST_PER_QUERY, 4)

    def _build_search_body(
        self,
        query: str,
        max_results: int,
        include_images: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": True,
            "include_raw_content": False,
        }
        if include_images:
            body["include_images"] = True
            body["include_image_descriptions"] = True
        return body

    @retry(
        retry=retry_if_exception_type(TavilyTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_images: bool = False,
    ) -> SearchResponse:
        headers = {
            "Content-Type": "application/json",
        }
        body = self._build_search_body(query, max_results, include_images)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{TAVILY_BASE_URL}/search",
                headers=headers,
                json=body,
            )

        if response.status_code == 429:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error="HTTP 429", request_key=query)
            raise TavilyTransientError("Rate limited")
        if response.status_code >= 500:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=query)
            raise TavilyTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=query)
            raise TavilyError(
                f"Tavily API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        results: list[SearchResult] = []
        for r in data.get("results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score", 0.0),
            ))

        images: list[ImageCandidate] = []
        seen: set[str] = set()
        for image in data.get("images", []):
            if isinstance(image, str):
                candidate = ImageCandidate(url=image)
            else:
                candidate = ImageCandidate(
                    url=image.get("url", ""),
                    description=image.get("description", ""),
                )
            if candidate.url and candidate.url not in seen:
                images.append(candidate)
                seen.add(candidate.url)
        for result_data in data.get("results", []):
            for image in result_data.get("images", []):
                if isinstance(image, str):
                    url = image
                    description = ""
                else:
                    url = image.get("url", "")
                    description = image.get("description", "")
                if url and url not in seen:
                    images.append(ImageCandidate(
                        url=url,
                        description=description,
                        source_url=result_data.get("url"),
                        source_title=result_data.get("title", ""),
                        score=result_data.get("score", 0.0),
                    ))
                    seen.add(url)

        cost = self.estimate_cost(1)
        record_cost_event(
            provider=self.name,
            operation="search",
            input_units=1,
            unit_type="queries",
            amount_usd=cost,
            amount_kind="estimated",
            pricing_source="configured_query_rate",
            request_key=query,
        )
        logger.info(
            f"Tavily search: '{query}' → {len(results)} results, ~${cost:.4f}"
        )

        return SearchResponse(
            query=query,
            results=results,
            images=images,
            provider=self.name,
            estimated_cost_usd=cost,
        )


class SerperProvider:
    name = "serper"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def estimate_cost(self, num_queries: int) -> float:
        return round(num_queries * 0.003, 4)

    @retry(
        retry=retry_if_exception_type(TavilyTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_images: bool = False,
    ) -> SearchResponse:
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }
        body = {"q": query, "num": max_results}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers=headers,
                json=body,
            )

        if response.status_code == 429:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error="HTTP 429", request_key=query)
            raise TavilyTransientError("Rate limited")
        if response.status_code >= 500:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=query)
            raise TavilyTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            record_cost_event(provider=self.name, operation="search", status="failed", pricing_source="request_failed", error=f"HTTP {response.status_code}", request_key=query)
            raise TavilyError(
                f"Serper API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        results: list[SearchResult] = []
        for r in data.get("organic", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                score=1.0 - (r.get("position", 0) * 0.1),
            ))

        cost = self.estimate_cost(1)
        record_cost_event(
            provider=self.name,
            operation="search",
            input_units=1,
            unit_type="queries",
            amount_usd=cost,
            amount_kind="estimated",
            pricing_source="configured_query_rate",
            request_key=query,
        )
        logger.info(
            f"Serper search: '{query}' → {len(results)} results, ~${cost:.4f}"
        )

        return SearchResponse(
            query=query,
            results=results,
            provider=self.name,
            estimated_cost_usd=cost,
        )
