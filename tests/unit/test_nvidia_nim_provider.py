from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.providers.llm.base import LLMError
from app.providers.llm.nvidia_nim_provider import (
    NvidiaNimProvider,
    NvidiaNimTransientError,
)


class ExampleResult(BaseModel):
    title: str
    score: int


def test_nvidia_request_uses_nim_chat_api_without_openrouter_fields() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer nvidia-key"
        return httpx.Response(
            200,
            json={
                "model": "qwen/qwen3.5-397b-a17b",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            },
        )

    provider = NvidiaNimProvider(
        api_key="nvidia-key",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(provider.complete("system", "user", temperature=0.2, max_tokens=200))

    assert result == "ok"
    assert captured["model"] == "qwen/qwen3.5-397b-a17b"
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert "models" not in captured
    assert "route" not in captured
    assert "provider" not in captured
    assert "response_format" not in captured


def test_nvidia_complete_structured_validates_json() -> None:
    responses = iter(['```json\n{"title":"Test","score":9}\n```'])
    provider = NvidiaNimProvider(api_key="test")
    provider.complete = lambda *args, **kwargs: _async_value(next(responses))

    result = asyncio.run(
        provider.complete_structured(
            "system",
            "user",
            ExampleResult,
            schema_name="example_result",
        )
    )

    assert result == ExampleResult(title="Test", score=9)


def test_nvidia_complete_structured_repairs_invalid_json() -> None:
    responses = iter(["not json", '{"title":"Fixed","score":7}'])
    prompts: list[str] = []
    provider = NvidiaNimProvider(api_key="test")

    async def complete(system_prompt: str, user_prompt: str, **kwargs) -> str:
        prompts.append(user_prompt)
        return next(responses)

    provider.complete = complete

    result = asyncio.run(
        provider.complete_structured(
            "system",
            "original task",
            ExampleResult,
            schema_name="example_result",
            max_repair_attempts=1,
        )
    )

    assert result.score == 7
    assert "Previous invalid response: not json" in prompts[1]


def test_nvidia_provider_rejects_multimodal_completion() -> None:
    provider = NvidiaNimProvider(api_key="test")

    with pytest.raises(LLMError, match="text-only"):
        asyncio.run(
            provider.complete_structured_with_images(
                "system",
                "user",
                [],
                ExampleResult,
                schema_name="example_result",
            )
        )


def test_nvidia_timeout_is_retried_and_has_a_readable_message() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("", request=request)

    provider = NvidiaNimProvider(
        api_key="test",
        timeout=0.01,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        NvidiaNimTransientError,
        match="timed out after 0.01 seconds",
    ):
        asyncio.run(provider.complete("system", "user"))

    assert attempts == 2


async def _async_value(value: str) -> str:
    return value
