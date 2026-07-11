from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings
from app.providers.search.base import SearchProvider
from app.providers.search.searxng_provider import SearXNGProvider


class SearXNGCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearXNGCheckResult:
    general_results: int
    image_results: int


async def run_check(provider: Optional[SearchProvider] = None) -> SearXNGCheckResult:
    settings = get_settings()
    resolved = provider or SearXNGProvider(
        base_url=settings.searxng_base_url,
        timeout=settings.searxng_timeout_seconds,
    )
    response = await resolved.search(
        "coffee beans",
        max_results=3,
        include_images=True,
    )
    if not response.results:
        raise SearXNGCheckError("SearXNG returned no general JSON results")
    if not response.images:
        raise SearXNGCheckError("SearXNG returned no image JSON results")
    return SearXNGCheckResult(
        general_results=len(response.results),
        image_results=len(response.images),
    )


def main() -> int:
    try:
        result = asyncio.run(run_check())
    except Exception as error:
        print(f"SearXNG check failed: {error}")
        return 1
    print(
        "SearXNG JSON search is ready: "
        f"{result.general_results} general results, {result.image_results} image results"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
