from __future__ import annotations

import app.config as config
from app.config import Settings
from app.providers.llm.openai_provider import LLMProvider
from app.providers.llm.nvidia_nim_provider import NvidiaNimProvider
import streamlit_app


def test_text_roles_use_openrouter_when_nvidia_switch_is_disabled(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        USE_NVIDIA_NIM_TEXT_LLM=False,
    )
    monkeypatch.setattr(config, "_settings", settings)

    providers = [
        config.get_llm_provider(),
        config.get_topic_llm_provider(),
        config.get_script_llm_provider(),
        config.get_direction_llm_provider(),
    ]

    assert all(isinstance(provider, LLMProvider) for provider in providers)


def test_text_roles_use_nvidia_nim_when_switch_is_enabled(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
    )
    monkeypatch.setattr(config, "_settings", settings)

    providers = [
        config.get_llm_provider(),
        config.get_topic_llm_provider(),
        config.get_script_llm_provider(),
        config.get_direction_llm_provider(),
    ]

    assert all(isinstance(provider, NvidiaNimProvider) for provider in providers)
    assert all(provider._models == [
        "deepseek-ai/deepseek-v4-pro",
        "minimaxai/minimax-m2.7",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ] for provider in providers)


def test_nvidia_selection_requires_nvidia_key_not_openrouter_key(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="",
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
    )
    monkeypatch.setattr(config, "_settings", settings)

    assert isinstance(config.get_llm_provider(), NvidiaNimProvider)


def test_missing_selected_text_provider_key_returns_none(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="",
    )
    monkeypatch.setattr(config, "_settings", settings)

    assert config.get_llm_provider() is None


def test_vision_stays_on_openrouter_when_nvidia_text_is_enabled(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
    )
    monkeypatch.setattr(config, "_settings", settings)

    provider = config.get_vision_llm_provider()

    assert isinstance(provider, LLMProvider)
    assert provider.name == "openrouter"


def test_requested_gemini_image_slug_is_the_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.image_model == "google/gemini-3.1-flash-lite-image"


def test_nvidia_timeout_is_configurable(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
        NVIDIA_NIM_TIMEOUT_SECONDS=345,
    )
    monkeypatch.setattr(config, "_settings", settings)

    provider = config.get_llm_provider()

    assert isinstance(provider, NvidiaNimProvider)
    assert provider._timeout == 345


def test_nvidia_fallback_models_are_trimmed_and_deduplicated(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
        NVIDIA_NIM_MODEL="primary/model",
        NVIDIA_NIM_FALLBACK_MODELS=" second/model, ,third/model,second/model ",
    )
    monkeypatch.setattr(config, "_settings", settings)

    provider = config.get_llm_provider()

    assert isinstance(provider, NvidiaNimProvider)
    assert provider._models == ["primary/model", "second/model", "third/model"]


def test_streamlit_text_factory_uses_configured_nvidia_provider(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
    )
    monkeypatch.setattr(streamlit_app, "get_settings", lambda: settings)
    streamlit_app.get_llm_provider.clear()

    provider = streamlit_app.get_llm_provider()

    streamlit_app.get_llm_provider.clear()
    assert isinstance(provider, NvidiaNimProvider)
