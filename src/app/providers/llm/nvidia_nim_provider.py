from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.providers.llm.base import LLMError, LLMProvider as BaseLLMProvider, LLMRepairError
from app.services.job_cost_ledger import record_cost_event

ModelT = TypeVar("ModelT", bound=BaseModel)


class NvidiaNimTransientError(LLMError):
    pass


class NvidiaNimProvider(BaseLLMProvider):
    name = "nvidia_nim"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-ai/deepseek-v4-pro",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout: float = 300.0,
        skills_content: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        fallback_models: Optional[list[str]] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._models = list(dict.fromkeys(
            candidate.strip()
            for candidate in [model, *(fallback_models or [])]
            if candidate.strip()
        ))
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._skills_content = skills_content or ""
        self._transport = transport

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None,
    ) -> float:
        return 0.0

    def _build_system_prompt(self, system_prompt: str) -> str:
        if self._skills_content:
            return f"{self._skills_content}\n\n---\n\n{system_prompt}"
        return system_prompt

    def _build_request_body(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": self._build_system_prompt(system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": False,
        }

    @staticmethod
    def _extract_json(raw: str) -> str:
        text = raw.strip()
        fenced = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", text, re.DOTALL)
        return fenced.group(1).strip() if fenced else text

    def _record_usage(
        self,
        data: dict[str, Any],
        operation: str,
        request_key: str,
        attempted_model: str,
    ) -> None:
        usage = data.get("usage", {}) or {}
        record_cost_event(
            provider=self.name,
            model=data.get("model", attempted_model),
            operation=operation,
            input_units=usage.get("prompt_tokens", 0),
            output_units=usage.get("completion_tokens", 0),
            unit_type="tokens",
            amount_usd=0.0,
            amount_kind="estimated",
            pricing_source="nvidia_api_trial_unpriced",
            request_key=request_key,
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
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        failures: list[NvidiaNimTransientError] = []
        for model in self._models:
            body = self._build_request_body(
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                model,
            )
            request_key = hashlib.sha256(
                json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )
            except httpx.TimeoutException as exc:
                message = f"NVIDIA NIM request timed out after {self._timeout:g} seconds"
                record_cost_event(
                    provider=self.name,
                    model=model,
                    operation="chat_completion",
                    status="failed",
                    pricing_source="request_failed",
                    error=message,
                    request_key=request_key,
                )
                failures.append(NvidiaNimTransientError(message))
                continue
            except httpx.TransportError as exc:
                detail = str(exc).strip() or "no details provided"
                message = f"NVIDIA NIM transport error: {type(exc).__name__}: {detail}"
                record_cost_event(
                    provider=self.name,
                    model=model,
                    operation="chat_completion",
                    status="failed",
                    pricing_source="request_failed",
                    error=message,
                    request_key=request_key,
                )
                failures.append(NvidiaNimTransientError(message))
                continue
            if response.status_code in {404, 429} or response.status_code >= 500:
                message = f"NVIDIA NIM unavailable: HTTP {response.status_code}"
                record_cost_event(
                    provider=self.name,
                    model=model,
                    operation="chat_completion",
                    status="failed",
                    pricing_source="request_failed",
                    error=f"HTTP {response.status_code}",
                    request_key=request_key,
                )
                failures.append(NvidiaNimTransientError(message))
                continue
            if response.status_code != 200:
                record_cost_event(
                    provider=self.name,
                    model=model,
                    operation="chat_completion",
                    status="failed",
                    pricing_source="request_failed",
                    error=f"HTTP {response.status_code}",
                    request_key=request_key,
                )
                raise LLMError(
                    f"NVIDIA NIM API error {response.status_code}: {response.text[:500]}"
                )
            data = response.json()
            self._record_usage(data, "chat_completion", request_key, model)
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError("NVIDIA NIM response did not contain message content") from exc
            if not isinstance(content, str):
                raise LLMError("NVIDIA NIM message content was not text")
            return content
        attempted = ", ".join(self._models)
        error = NvidiaNimTransientError(
            f"NVIDIA NIM unavailable after attempting models: {attempted}"
        )
        if failures:
            raise error from failures[-1]
        raise error

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        max_repair_attempts: int = 2,
    ) -> dict:
        prompt = f"{user_prompt}\n\nReturn only one valid JSON object with no markdown."
        raw = await self.complete(
            system_prompt,
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for attempt in range(max_repair_attempts + 1):
            try:
                value = json.loads(self._extract_json(raw))
                if not isinstance(value, dict):
                    raise ValueError("Response is not a JSON object")
                return value
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt >= max_repair_attempts:
                    raise LLMRepairError(
                        f"Failed to parse NVIDIA NIM JSON after {attempt + 1} attempts: {exc}"
                    ) from exc
                raw = await self.complete(
                    "You repair JSON. Return only one valid JSON object.",
                    f"Fix this invalid JSON:\n{raw}",
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
        raise LLMRepairError("unreachable")

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
        schema = json.dumps(model_type.model_json_schema(), ensure_ascii=False)
        base_prompt = (
            f"{user_prompt}\n\nReturn only valid JSON matching schema {schema_name}:\n{schema}"
        )
        prompt = base_prompt
        for attempt in range(max_repair_attempts + 1):
            raw = await self.complete(
                system_prompt,
                prompt,
                temperature=temperature if attempt == 0 else 0.0,
                max_tokens=max_tokens,
            )
            try:
                return model_type.model_validate_json(self._extract_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if attempt >= max_repair_attempts:
                    raise LLMRepairError(
                        f"Failed to validate {schema_name} after {attempt + 1} attempts: {exc}"
                    ) from exc
                prompt = (
                    f"{base_prompt}\n\nYour previous response failed validation: {exc}\n"
                    f"Previous invalid response: {raw}\n"
                    "Return corrected JSON only."
                )
        raise LLMRepairError("unreachable")

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
        max_repair_attempts: int = 2,
    ) -> ModelT:
        raise LLMError("NVIDIA NIM is configured as a text-only provider")
