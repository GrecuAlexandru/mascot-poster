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
                "model": "deepseek-ai/deepseek-v4-pro",
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
    assert captured["model"] == "deepseek-ai/deepseek-v4-pro"
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


def test_nvidia_timeout_advances_to_fallback_model() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == "primary/model":
            raise httpx.ReadTimeout("", request=request)
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": "fallback worked"}}],
                "usage": {},
            },
        )

    provider = NvidiaNimProvider(
        api_key="test",
        model="primary/model",
        fallback_models=["fallback/model"],
        timeout=0.01,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(provider.complete("system", "user"))

    assert result == "fallback worked"
    assert requested == ["primary/model", "fallback/model"]


def test_nvidia_provider_falls_back_in_order_for_unavailable_models() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == "deepseek-ai/deepseek-v4-pro":
            return httpx.Response(429)
        if model == "minimaxai/minimax-m2.7":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": "fallback worked"}}],
                "usage": {},
            },
        )

    provider = NvidiaNimProvider(
        api_key="test",
        model="deepseek-ai/deepseek-v4-pro",
        fallback_models=[
            "minimaxai/minimax-m2.7",
            "deepseek-ai/deepseek-v4-pro",
            "nvidia/nemotron-3-ultra-550b-a55b",
        ],
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(provider.complete("system", "user"))

    assert result == "fallback worked"
    assert requested == [
        "deepseek-ai/deepseek-v4-pro",
        "minimaxai/minimax-m2.7",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ]
    assert provider._models == requested


def test_nvidia_transport_and_server_errors_advance_models() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == "primary/model":
            raise httpx.ConnectError("unavailable", request=request)
        if model == "second/model":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            },
        )

    provider = NvidiaNimProvider(
        api_key="test",
        model="primary/model",
        fallback_models=["second/model", "third/model"],
        transport=httpx.MockTransport(handler),
    )

    assert asyncio.run(provider.complete("system", "user")) == "ok"
    assert requested == ["primary/model", "second/model", "third/model"]


def test_nvidia_non_retryable_client_error_fails_without_fallback() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(json.loads(request.content)["model"])
        return httpx.Response(400, text="bad request")

    provider = NvidiaNimProvider(
        api_key="test",
        model="primary/model",
        fallback_models=["fallback/model"],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMError, match="API error 400"):
        asyncio.run(provider.complete("system", "user"))

    assert requested == ["primary/model"]


def test_nvidia_exhaustion_lists_all_attempted_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    provider = NvidiaNimProvider(
        api_key="test",
        model="primary/model",
        fallback_models=["second/model", "third/model"],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(NvidiaNimTransientError) as captured:
        asyncio.run(provider.complete("system", "user"))

    message = str(captured.value)
    assert "primary/model" in message
    assert "second/model" in message
    assert "third/model" in message


async def _async_value(value: str) -> str:
    return value
