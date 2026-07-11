from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMRepairError(LLMError):
    pass


class LLMProvider:
    name = "openrouter"

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None,
    ) -> float:
        return 0.0

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: Optional[dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        raise NotImplementedError

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        max_repair_attempts: int = 2,
    ) -> dict:
        raise NotImplementedError

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        model_type: type[ModelT],
        *,
        schema_name: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_repair_attempts: int = 2,
    ) -> ModelT:
        raise NotImplementedError

    async def complete_structured_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path],
        model_type: type[ModelT],
        *,
        schema_name: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> ModelT:
        raise NotImplementedError
