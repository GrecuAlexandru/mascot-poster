from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, Field, field_validator


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    score: float = 0.0

    @field_validator("title", "url", "snippet", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str:
        return value if isinstance(value, str) else ""


class ImageCandidate(BaseModel):
    url: str
    description: str = ""
    source_url: Optional[str] = None
    source_title: str = ""
    score: float = 0.0

    @field_validator("url", "description", "source_title", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str:
        return value if isinstance(value, str) else ""


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    images: list[ImageCandidate] = Field(default_factory=list)
    provider: str = ""
    estimated_cost_usd: float = 0.0


class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_images: bool = False,
    ) -> SearchResponse: ...

    def estimate_cost(self, num_queries: int) -> float: ...
