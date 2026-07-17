# NVIDIA NIM Model Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every NVIDIA NIM text completion try DeepSeek, MiniMax, and Nemotron in order when a model is unavailable.

**Architecture:** Extend `NvidiaNimProvider` with an ordered, deduplicated model chain. A completion attempts each model once for availability failures and records costs against the attempted model; configuration keeps the existing primary-model variable and adds a comma-separated fallback-model variable.

**Tech Stack:** Python 3.12+, httpx, Pydantic Settings, pytest

## Global Constraints

- Model order is `deepseek-ai/deepseek-v4-pro`, `minimaxai/minimax-m2.7`, `nvidia/nemotron-3-ultra-550b-a55b`.
- Advance only for HTTP `404`, HTTP `429`, HTTP `5xx`, timeout, or transport failure.
- Other HTTP `4xx` responses fail immediately.
- Each model is attempted once per completion call.
- Existing OpenRouter, vision, image, job retry, and Telegram behavior remains unchanged.
- Preserve all unrelated working-tree changes.

---

### Task 1: Ordered provider fallback

**Files:**
- Modify: `tests/unit/test_nvidia_nim_provider.py`
- Modify: `src/app/providers/llm/nvidia_nim_provider.py`

**Interfaces:**
- Consumes: existing `NvidiaNimProvider.complete(...) -> str`
- Produces: `NvidiaNimProvider(..., fallback_models: Optional[list[str]] = None)` and ordered `provider._models`

- [ ] **Step 1: Write failing tests for ordered fallback and deduplication**

Add tests whose mock transport returns `429` for DeepSeek, `404` for MiniMax, and success for Nemotron. Assert the request model sequence and final text. Construct the provider with a duplicate fallback and assert `_models` preserves only the first occurrence.

```python
def test_nvidia_provider_falls_back_in_order_for_unavailable_models() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == "deepseek-ai/deepseek-v4-pro":
            return httpx.Response(429)
        if model == "minimaxai/minimax-m2.7":
            return httpx.Response(404)
        return httpx.Response(200, json={
            "model": model,
            "choices": [{"message": {"content": "fallback worked"}}],
            "usage": {},
        })

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

    assert asyncio.run(provider.complete("system", "user")) == "fallback worked"
    assert requested == [
        "deepseek-ai/deepseek-v4-pro",
        "minimaxai/minimax-m2.7",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ]
    assert provider._models == requested
```

- [ ] **Step 2: Run the ordered-fallback test and verify RED**

Run: `python -m pytest tests/unit/test_nvidia_nim_provider.py::test_nvidia_provider_falls_back_in_order_for_unavailable_models -v`

Expected: FAIL because `fallback_models` is not an accepted constructor argument.

- [ ] **Step 3: Add failing tests for exhaustion, transport failures, and non-retryable errors**

Add focused tests that assert timeout/transport/`5xx` advance, all-unavailable errors list all model IDs, and HTTP `400` performs exactly one request and raises `LLMError`.

- [ ] **Step 4: Run the provider test file and verify RED**

Run: `python -m pytest tests/unit/test_nvidia_nim_provider.py -v`

Expected: new fallback tests fail while existing behavior tests remain green.

- [ ] **Step 5: Implement the minimal provider model chain**

Change the provider to build an ordered unique tuple from the primary and fallback models. Pass the attempted model into request-body creation and usage recording. Replace the same-model Tenacity retry decorator with a loop that advances for `404`, `429`, `5xx`, timeout, and transport errors. Raise immediately for other non-`200` responses and malformed successful responses. After exhausting the chain, raise `NvidiaNimTransientError` with every attempted model and chain the final availability error.

- [ ] **Step 6: Run provider tests and verify GREEN**

Run: `python -m pytest tests/unit/test_nvidia_nim_provider.py -v`

Expected: all provider tests PASS.

- [ ] **Step 7: Commit the provider behavior**

```bash
git add src/app/providers/llm/nvidia_nim_provider.py tests/unit/test_nvidia_nim_provider.py
git commit -m "feat: add NVIDIA NIM model fallback"
```

### Task 2: Configure the default chain

**Files:**
- Modify: `tests/unit/test_llm_provider_selection.py`
- Modify: `src/app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `NvidiaNimProvider(..., fallback_models=list[str])`
- Produces: `Settings.nvidia_nim_fallback_models: str` using alias `NVIDIA_NIM_FALLBACK_MODELS`

- [ ] **Step 1: Write failing configuration tests**

Assert the Settings defaults and constructed provider chain:

```python
def test_nvidia_default_model_chain_is_ordered(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        USE_NVIDIA_NIM_TEXT_LLM=True,
        NVIDIA_NIM_API_KEY="nvidia-key",
    )
    monkeypatch.setattr(config, "_settings", settings)

    provider = config.get_llm_provider()

    assert isinstance(provider, NvidiaNimProvider)
    assert provider._models == [
        "deepseek-ai/deepseek-v4-pro",
        "minimaxai/minimax-m2.7",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ]
```

Also construct Settings with whitespace and empty comma-separated entries and assert they are parsed away.

- [ ] **Step 2: Run the configuration test and verify RED**

Run: `python -m pytest tests/unit/test_llm_provider_selection.py::test_nvidia_default_model_chain_is_ordered -v`

Expected: FAIL because the current default is Qwen and no fallback list is propagated.

- [ ] **Step 3: Implement Settings and factory propagation**

Set `NVIDIA_NIM_MODEL` default to DeepSeek. Add a string setting for the two comma-separated fallback models. In `_build_text_llm_provider`, split on commas, trim whitespace, drop empty entries, and pass the resulting list to `NvidiaNimProvider`.

- [ ] **Step 4: Update the example environment**

Set:

```dotenv
NVIDIA_NIM_MODEL=deepseek-ai/deepseek-v4-pro
NVIDIA_NIM_FALLBACK_MODELS=minimaxai/minimax-m2.7,nvidia/nemotron-3-ultra-550b-a55b
```

- [ ] **Step 5: Run configuration and provider tests and verify GREEN**

Run: `python -m pytest tests/unit/test_llm_provider_selection.py tests/unit/test_nvidia_nim_provider.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit configuration**

```bash
git add .env.example src/app/config.py tests/unit/test_llm_provider_selection.py
git commit -m "feat: configure NVIDIA fallback chain"
```

### Task 3: Regression verification and mini-PC deployment

**Files:**
- Verify: `src/app/providers/llm/nvidia_nim_provider.py`
- Verify: `src/app/config.py`
- Verify: `tests/unit/test_nvidia_nim_provider.py`
- Verify: `tests/unit/test_llm_provider_selection.py`

**Interfaces:**
- Consumes: committed provider and configuration behavior from Tasks 1 and 2
- Produces: verified local behavior and rebuilt mini-PC application containers

- [ ] **Step 1: Run focused regression tests**

Run: `python -m pytest tests/unit/test_nvidia_nim_provider.py tests/unit/test_llm_provider_selection.py tests/unit/test_reference_generation.py -v`

Expected: all tests PASS.

- [ ] **Step 2: Run the full unit suite**

Run: `python -m pytest tests/unit/ -v`

Expected: all tests PASS.

- [ ] **Step 3: Sync committed fallback files to the clean matching mini-PC base**

Verify remote status first. Transfer only `.env.example`, `src/app/config.py`, `src/app/providers/llm/nvidia_nim_provider.py`, and their tests. Do not overwrite `/home/alexandru/secrets/mascot-poster.env`; its existing primary model remains DeepSeek and code defaults supply the two fallbacks.

- [ ] **Step 4: Rebuild and recreate application containers**

Run remotely:

```bash
cd /home/alexandru/docker/mascot-poster
MASCOT_ENV_FILE=/home/alexandru/secrets/mascot-poster.env \
docker compose --env-file /home/alexandru/secrets/mascot-poster.env build api worker bot cleanup
MASCOT_ENV_FILE=/home/alexandru/secrets/mascot-poster.env \
docker compose --env-file /home/alexandru/secrets/mascot-poster.env up -d --force-recreate api worker bot cleanup
```

- [ ] **Step 5: Verify deployment**

Confirm the API returns HTTP `200`, all four application containers remain running, the worker source hashes match local files, and the constructed provider exposes the required three-model order without printing API keys.
