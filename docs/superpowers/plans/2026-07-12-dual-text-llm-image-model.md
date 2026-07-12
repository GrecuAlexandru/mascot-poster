# Dual Text LLM and Image Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a boolean OpenRouter/NVIDIA NIM switch for all text-only LLM stages and use `google/gemini-3.1-flash-lite-image` for image generation.

**Architecture:** Add a dedicated NVIDIA NIM adapter behind the existing LLM interface and centralize text-provider construction in configuration. Keep vision and image generation on OpenRouter so the text switch cannot remove required multimodal capability.

**Tech Stack:** Python 3.11+, Pydantic Settings, httpx, tenacity, pytest

## Global Constraints

- Use `USE_NVIDIA_NIM_TEXT_LLM` as the boolean switch.
- Use `qwen/qwen3.5-397b-a17b` through `https://integrate.api.nvidia.com/v1` when enabled.
- Keep all secrets in environment variables.
- Keep vision validation on OpenRouter.
- Use the exact image slug `google/gemini-3.1-flash-lite-image`.
- Preserve provider interfaces, type hints, and the Pydantic repair loop.
- Add no source-code comments.

---

### Task 1: Configuration and provider selection

**Files:**
- Modify: `tests/unit/test_reference_assets.py`
- Modify: `src/app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `Settings.use_nvidia_nim_text_llm: bool`, NVIDIA settings fields, and text-role factories returning the selected provider.
- Consumes: Existing `get_llm_provider`, `get_topic_llm_provider`, `get_script_llm_provider`, and `get_direction_llm_provider` call sites.

- [ ] **Step 1: Write failing tests** for the default image slug, OpenRouter selection when disabled, NVIDIA selection for every text role when enabled, and missing selected credentials.
- [ ] **Step 2: Run the focused tests** with `python -m pytest tests/unit/test_reference_assets.py -k "nvidia or text_provider or openrouter_image_provider" -v` and confirm failures are caused by absent settings and provider routing.
- [ ] **Step 3: Implement settings and centralized provider construction** with `USE_NVIDIA_NIM_TEXT_LLM`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_BASE_URL`, and `NVIDIA_NIM_MODEL`; retain OpenRouter for `get_vision_llm_provider` and `get_image_provider`.
- [ ] **Step 4: Update `.env.example`** with the new switch and NVIDIA variables and change `OPENROUTER_IMAGE_MODEL` to the exact requested slug.
- [ ] **Step 5: Run the focused tests** and confirm they pass.

### Task 2: NVIDIA NIM adapter

**Files:**
- Create: `src/app/providers/llm/nvidia_nim_provider.py`
- Create: `tests/unit/test_nvidia_nim_provider.py`

**Interfaces:**
- Produces: `NvidiaNimProvider(BaseLLMProvider)` with `complete`, `complete_json`, `complete_structured`, and unsupported multimodal completion behavior.
- Consumes: NVIDIA Chat Completions responses and existing Pydantic model types.

- [ ] **Step 1: Write failing request-shape tests** asserting the NIM URL, bearer authentication, selected model, `chat_template_kwargs={"enable_thinking": false}`, no OpenRouter routing fields, and no unsupported response-format field.
- [ ] **Step 2: Write failing structured-output tests** for valid JSON, fenced JSON extraction, Pydantic validation, repair after malformed output, retryable HTTP responses, and clear unsupported image-completion behavior.
- [ ] **Step 3: Run `python -m pytest tests/unit/test_nvidia_nim_provider.py -v`** and confirm import/behavior failures.
- [ ] **Step 4: Implement the minimal typed adapter** using httpx, tenacity, cost-ledger events, prompt-enforced JSON, Pydantic validation, and repair attempts.
- [ ] **Step 5: Re-run the adapter tests** and confirm they pass.

### Task 3: Integration and regression verification

**Files:**
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: Provider factories from `src/app/config.py`.
- Produces: Clear provider-neutral configuration errors and a service graph using the selected text provider for every text-only stage.

- [ ] **Step 1: Write a failing integration test** that builds the configured provider graph under both switch values and verifies vision remains OpenRouter.
- [ ] **Step 2: Replace OpenRouter-specific configuration error wording** with text-provider, vision-provider, and image-provider wording.
- [ ] **Step 3: Run focused configuration and pipeline tests** with `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py tests/unit/test_nvidia_nim_provider.py -v`.
- [ ] **Step 4: Run the complete suite** with `python -m pytest tests/ -v` and resolve only regressions caused by this feature.
- [ ] **Step 5: Inspect the final diff** to confirm secrets are absent, the exact requested slug is preserved, and unrelated working-tree changes were not overwritten.
