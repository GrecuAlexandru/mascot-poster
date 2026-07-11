# Bundled SearXNG Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run SearXNG locally through Docker and make it the default zero-incremental-query-cost source and image search provider.

**Architecture:** Add a SearXNG container plus a repository-owned settings file. Implement `SearXNGProvider` behind `SearchProvider`, select it through typed settings, record separate zero-cost general/image requests, and retain Tavily/Serper only when explicitly configured.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, tenacity, Docker Compose, SearXNG, pytest, Streamlit.

## Global Constraints

- SearXNG is the default `SEARCH_PROVIDER` and needs no `SEARCH_API_KEY`.
- Research and image discovery use SearXNG JSON endpoints only.
- General and image requests are separate, zero-incremental-query-cost ledger events.
- Tavily and Serper remain explicit opt-in providers; no automatic paid fallback is permitted.
- Host Streamlit uses `http://localhost:8080`; Docker API/worker use `http://searxng:8080`.
- Preserve user-owned mascot calibration, mascot PNG, topic history, and cost-export CSV changes.

---

### Task 1: Provider Normalization and Zero-Cost Events

**Files:**
- Create: `src/app/providers/search/searxng_provider.py`
- Modify: `tests/unit/test_reference_assets.py`
- Modify: `tests/unit/test_job_cost_ledger.py`

**Interfaces:**
- Produces: `SearXNGProvider(base_url: str, timeout: float = 30.0)`, `search(query, max_results, include_images) -> SearchResponse`, `estimate_cost(num_queries) -> 0.0`.

- [ ] **Step 1: Write failing normalization tests**

```python
def test_searxng_maps_general_and_image_json_to_search_response():
    provider = SearXNGProvider("http://search.test")
    provider._get_json = AsyncMock(side_effect=[general_payload, image_payload])
    response = asyncio.run(provider.search("coffee", max_results=5, include_images=True))
    assert response.provider == "searxng"
    assert response.results[0].url == "https://example.com/coffee"
    assert response.images[0].url == "https://cdn.example.com/coffee.png"
    assert response.images[0].source_url == "https://example.com/coffee"
```

Add cases for duplicate URLs, `img_src` versus `thumbnail_src`, malformed rows, and one zero-dollar ledger event for each category request.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_job_cost_ledger.py -k searxng -v`

Expected: collection fails because `SearXNGProvider` does not exist.

- [ ] **Step 3: Implement the provider**

Issue `GET /search?format=json&categories=general&q=<query>&pageno=1`. If images are requested, concurrently issue `categories=images`. Normalize `results`, preferring `img_src` over `thumbnail_src`, discard malformed entries, deduplicate canonical URLs, and retain `source_url`/metadata.

Use tenacity for transient `429` and `5xx` errors. Raise a dedicated error for unreachable service, invalid JSON, disabled JSON format, and non-success responses. Record success and failed requests with `provider="searxng"`, `operation="web_search"` or `"image_search"`, `amount_usd=0.0`, and `pricing_source="self_hosted_no_query_fee"`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_job_cost_ledger.py -k searxng -v`

```powershell
git add src/app/providers/search/searxng_provider.py tests/unit/test_reference_assets.py tests/unit/test_job_cost_ledger.py
git commit -m "add searxng search provider"
```

---

### Task 2: Settings, Factory, and Preflight

**Files:**
- Modify: `src/app/config.py`
- Modify: `.env.example`
- Modify: `streamlit_app.py`
- Modify: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Consumes: `SEARCH_PROVIDER`, `SEARXNG_BASE_URL`, `SEARXNG_TIMEOUT_SECONDS`.
- Produces: `get_search_provider()` returning SearXNG without an API key and `_reference_preflight()` provider-specific diagnostics.

- [ ] **Step 1: Write failing selection and preflight tests**

```python
def test_searxng_is_default_and_needs_no_search_api_key():
    settings = Settings(_env_file=None, SEARCH_PROVIDER="searxng")
    assert isinstance(get_search_provider(settings), SearXNGProvider)
    assert _reference_preflight(settings, "ro") == [
        "Missing OPENROUTER_API_KEY", "Missing ELEVENLABS_API_KEY", "Missing ELEVENLABS_VOICE_ID_RO", "SearXNG is unavailable at http://localhost:8080"
    ]
```

Add an assertion that Tavily and Serper still require `SEARCH_API_KEY`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_assets.py -k "searxng or preflight" -v`

Expected: FAIL because settings and factory do not recognize SearXNG.

- [ ] **Step 3: Implement settings and selection**

Set `search_provider` default to `searxng`; add typed base URL and timeout fields. Select `SearXNGProvider` before the paid-key check. Keep Tavily/Serper behavior unchanged when selected. Add `.env.example` values and provider-specific preflight messages.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_generation.py -v`

```powershell
git add src/app/config.py .env.example streamlit_app.py tests/unit/test_reference_assets.py
git commit -m "configure searxng as default search"
```

---

### Task 3: Docker Service and Local Smoke Test

**Files:**
- Create: `searxng/settings.yml`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Create: `scripts/check_searxng.py`
- Modify: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `docker compose up -d searxng`, host endpoint `http://localhost:8080`, and `python scripts/check_searxng.py` returning zero only for valid JSON general/image responses.

- [ ] **Step 1: Write failing configuration and smoke-command tests**

Assert Compose declares `searxng`, exposes `8080:8080`, mounts `searxng/settings.yml`, and the settings file enables `json`, `general`, and `images`. Test the smoke checker with fake provider results.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_assets.py -k searxng -v`

Expected: FAIL because no container settings or smoke checker exists.

- [ ] **Step 3: Add container configuration**

Use `searxng/searxng:latest`, mount settings read-only, provide an environment-substituted secret key, map host port 8080, and configure a health check. API and worker receive `SEARXNG_BASE_URL=http://searxng:8080` while host defaults stay on localhost.

- [ ] **Step 4: Add smoke check and documentation**

The script calls `SearXNGProvider.search` for one general and one image query, prints normalized counts and exits nonzero on no JSON response. README documents start, stop, browser URL, health check, and the fact that local operations still consume host resources despite zero provider query cost.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
python -m pytest tests/unit/test_reference_assets.py -k searxng -v
docker compose up -d searxng
python scripts/check_searxng.py
docker compose ps searxng
```

```powershell
git add docker-compose.yml searxng/settings.yml scripts/check_searxng.py README.md tests/unit/test_reference_assets.py
git commit -m "bundle local searxng service"
```

---

### Task 4: End-to-End Verification and Publication

**Files:**
- Modify: `docs/superpowers/plans/2026-07-11-bundled-searxng-search-implementation.md`

**Interfaces:**
- Produces: passing full suite, successful local SearXNG smoke test, zero-cost SearXNG events, and pushed `main` branch.

- [ ] **Step 1: Run complete verification**

```powershell
python -m compileall -q src scripts streamlit_app.py
python -m pytest tests/ -v
python scripts/validate_assets.py
python scripts/check_searxng.py
```

- [ ] **Step 2: Validate no paid fallback**

Run a fake-provider one-click generation and assert its cost report contains `searxng` zero-cost events and no Tavily event unless `SEARCH_PROVIDER=tavily` is explicitly selected.

- [ ] **Step 3: Commit and push**

```powershell
git add docs/superpowers/plans/2026-07-11-bundled-searxng-search-implementation.md src tests scripts docker-compose.yml searxng README.md .env.example streamlit_app.py
git commit -m "complete bundled searxng integration"
git push origin main
```

## Plan Self-Review

- Spec coverage: Docker deployment, host/container URL separation, JSON general/image normalization, zero-cost ledger entries, explicit paid-provider selection, preflight, failure behavior, smoke testing, and no automatic paid fallback map to Tasks 1–4.
- Placeholder scan: no deferred work or unspecified acceptance criteria remain.
- Type consistency: `SearXNGProvider`, `SearchResponse`, `get_search_provider`, `SEARXNG_BASE_URL`, and `scripts/check_searxng.py` use consistent names across tasks.
