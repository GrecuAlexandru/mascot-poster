from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, Field


class GeneratedImage(BaseModel):
    path: Path
    prompt: str = ""
    width: int = 0
    height: int = 0
    provider: str = ""
    estimated_cost_usd: float = 0.0
    cached: bool = False


class ImageProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int = 1024,
        height: int = 1024,
    ) -> GeneratedImage: ...

    def estimate_cost(self, count: int = 1) -> float: ...
