from __future__ import annotations

import json
import logging
from typing import Any, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.llm.base import LLMError, LLMProvider as BaseLLMProvider, LLMRepairError

logger = logging.getLogger(__name__)

_COST_PER_1M_INPUT = {
    "mistralai/mistral-small-3.2-24b-instruct": 0.075,
    "mistralai/mistral-small-24b-instruct-2501": 0.075,
    "qwen/qwen3-235b-a22b-2507": 0.09,
    "qwen/qwen3-32b": 0.08,
    "google/gemini-2.5-flash-lite": 0.10,
    "openai/gpt-4o-mini": 0.15,
    "openai/gpt-4o": 2.5,
    "deepseek/deepseek-v3.2": 0.214,
    "deepseek/deepseek-v4-flash": 0.084,
    "deepseek/deepseek-v4-pro": 0.435,
    "qwen/qwen3.5-flash-02-23": 0.065,
}
_COST_PER_1M_OUTPUT = {
    "mistralai/mistral-small-3.2-24b-instruct": 0.20,
    "mistralai/mistral-small-24b-instruct-2501": 0.20,
    "qwen/qwen3-235b-a22b-2507": 0.10,
    "qwen/qwen3-32b": 0.28,
    "google/gemini-2.5-flash-lite": 0.40,
    "openai/gpt-4o-mini": 0.60,
    "openai/gpt-4o": 10.0,
    "deepseek/deepseek-v3.2": 0.322,
    "deepseek/deepseek-v4-flash": 0.168,
    "deepseek/deepseek-v4-pro": 0.87,
    "qwen/qwen3.5-flash-02-23": 0.26,
}

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMTransientError(LLMError):
    pass


class LLMProvider(BaseLLMProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek/deepseek-v4-flash",
        fallback_models: Optional[list[str]] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 90.0,
        skills_content: Optional[str] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._fallback_models = list(fallback_models or [])
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._skills_content = skills_content or ""

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None,
    ) -> float:
        m = model or self._model
        in_cost = _COST_PER_1M_INPUT.get(m, 0.10)
        out_cost = _COST_PER_1M_OUTPUT.get(m, 0.20)
        return round(
            (input_tokens / 1_000_000) * in_cost
            + (output_tokens / 1_000_000) * out_cost,
            6,
        )

    def _build_system_prompt(self, system_prompt: str) -> str:
        if self._skills_content:
            return f"{self._skills_content}\n\n---\n\n{system_prompt}"
        return system_prompt

    def _build_request_body(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._build_system_prompt(system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        models = [self._model, *self._fallback_models]
        if self._fallback_models:
            body["models"] = models
            body["route"] = "fallback"
        else:
            body["model"] = self._model
        if response_format:
            body["response_format"] = response_format
            if response_format.get("type") == "json_schema":
                body["provider"] = {"require_parameters": True}
        return body

    @retry(
        retry=retry_if_exception_type(LLMTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: Optional[dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self._base_url:
            headers["HTTP-Referer"] = "https://localhost:8000"
            headers["X-Title"] = "Automated Short Video Platform"

        body = self._build_request_body(
            system_prompt,
            user_prompt,
            response_format,
            temperature,
            max_tokens,
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=body,
            )

        if response.status_code == 429:
            raise LLMTransientError("Rate limited")
        if response.status_code >= 500:
            raise LLMTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            raise LLMError(
                f"LLM API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        usage = data.get("usage", {})
        response_model = data.get("model", self._model)
        cost = self.estimate_cost(
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            response_model,
        )
        logger.info(
            f"LLM completion [{response_model}]: "
            f"{usage.get('total_tokens', 0)} tokens, ~${cost:.4f}"
        )

        return content

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
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": model_type.model_json_schema(),
            },
        }
        prompt = user_prompt
        for attempt in range(max_repair_attempts + 1):
            raw = await self.complete(
                system_prompt=system_prompt,
                user_prompt=prompt,
                response_format=response_format,
                temperature=temperature if attempt == 0 else 0.0,
                max_tokens=max_tokens,
            )
            try:
                return model_type.model_validate_json(raw)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if attempt >= max_repair_attempts:
                    raise LLMRepairError(
                        f"Failed to validate {schema_name} after {attempt + 1} attempts: {exc}"
                    ) from exc
                prompt = (
                    f"Return a corrected value that follows the required schema. "
                    f"Validation error: {exc}. Invalid response: {raw}"
                )
        raise LLMRepairError("unreachable")

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        max_repair_attempts: int = 2,
    ) -> dict:
        raw = await self.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )

        for attempt in range(max_repair_attempts + 1):
            try:
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("Response is not a JSON object")
                return result
            except (json.JSONDecodeError, ValueError) as e:
                if attempt >= max_repair_attempts:
                    raise LLMRepairError(
                        f"Failed to parse JSON after {max_repair_attempts + 1} attempts: {e}\n"
                        f"Raw output (first 500 chars): {raw[:500]}"
                    )
                logger.warning(
                    f"JSON parse failed (attempt {attempt + 1}), "
                    f"requesting repair..."
                )
                raw = await self.complete(
                    system_prompt=(
                        "You are a JSON repair tool. Fix the malformed JSON. "
                        "Return ONLY valid JSON, no markdown fences, no extra text."
                    ),
                    user_prompt=f"Fix this JSON:\n{raw}",
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=max_tokens,
                )

        raise LLMRepairError("unreachable")
