# Bundled SearXNG Search Design

## Goal

Replace paid-by-query Tavily search in the one-click reference workflow with a repository-managed SearXNG instance that supports research sources and product-image discovery without a per-query API charge.

## Deployment

`docker-compose.yml` gains a `searxng` service using the official `searxng/searxng` image. It listens on container port `8080` and is exposed on host port `8080`. A repository-owned settings file is mounted read-only into the container.

The configuration enables:

- JSON and HTML response formats;
- `general` and `images` search categories;
- safe search at level 1;
- local-only deployment defaults suitable for this application;
- no public-instance rate limiter;
- a generated environment-provided secret key rather than a committed secret;
- the existing Docker network shared by the API and worker services.

The application uses `http://localhost:8080` when Streamlit runs on the Windows host. Docker services override the URL to `http://searxng:8080`. SearXNG remains independently accessible at `http://localhost:8080` for diagnostics.

## Provider Contract

Add `SearXNGProvider` behind the existing `SearchProvider` protocol:

```python
class SearXNGProvider:
    name = "searxng"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_images: bool = False,
    ) -> SearchResponse: ...

    def estimate_cost(self, num_queries: int) -> float:
        return 0.0
```

Normal searches issue one JSON request with `categories=general`. When `include_images=True`, the provider concurrently requests `general` and `images`, combines the responses, normalizes them into `SearchResult` and `ImageCandidate`, and deduplicates by canonical URL.

General results map:

- `title` to `SearchResult.title`;
- `url` to `SearchResult.url`;
- `content` to `SearchResult.snippet`;
- `score` to `SearchResult.score`.

Image results accept SearXNG variants such as `img_src`, `thumbnail_src`, `url`, and `source`. The full image URL is preferred over a thumbnail. The result-page URL becomes `source_url`; title/content become candidate metadata. Malformed and URL-less rows are discarded.

## Configuration and Selection

Add environment settings:

```dotenv
SEARCH_PROVIDER=searxng
SEARXNG_BASE_URL=http://localhost:8080
SEARXNG_TIMEOUT_SECONDS=30
SEARXNG_SECRET_KEY=replace-with-a-local-random-value
```

`SEARCH_API_KEY` becomes optional when `SEARCH_PROVIDER=searxng`. It remains required for Tavily and Serper. `get_search_provider()` selects SearXNG without an API key, while preserving the existing paid providers as explicit alternatives.

The default provider changes from `tavily` to `searxng`. Existing installations that explicitly set `SEARCH_PROVIDER=tavily` continue to behave as before.

## Health and Preflight

The provider exposes a lightweight asynchronous health check that requests the SearXNG configuration or a minimal JSON search. Streamlit preflight distinguishes:

- missing API key for paid providers;
- malformed SearXNG URL;
- unreachable local SearXNG instance;
- JSON format disabled by the SearXNG configuration.

The interface does not silently switch to Tavily. A SearXNG failure produces a stage-specific message with the exact start command:

```powershell
docker compose up -d searxng
```

This prevents an unavailable free provider from unexpectedly creating paid requests.

## Cost Accounting

Each SearXNG HTTP request creates a cost-ledger event:

- provider: `searxng`;
- operation: `web_search` or `image_search`;
- units: one request;
- amount: `$0.00`;
- kind: estimated;
- pricing source: `self_hosted_no_query_fee`;
- status, latency, and failure details when applicable.

General and image-category calls are separate events because `include_images=True` creates two HTTP requests. Local infrastructure cost is not presented as zero in an accounting sense; the report labels this specifically as no incremental query fee, excluding electricity and host costs.

## Resilience

Transient network errors, HTTP 429, and server errors receive up to three attempts with exponential backoff. Invalid JSON, disabled JSON output, and schema-invalid responses fail immediately with actionable messages. Failed attempts remain in the cost ledger.

Search-result quality gates remain unchanged. If SearXNG returns no acceptable product images, the existing OpenRouter image-generation fallback is used. Tavily is not used automatically.

## Testing

Unit tests cover:

- general-result normalization;
- image-result normalization for all supported field variants;
- general/image concurrency;
- URL deduplication;
- malformed rows and null metadata;
- zero-cost success, failure, and retry events;
- paid-provider API-key requirements remaining intact;
- SearXNG requiring no API key;
- host and Docker URL configuration;
- Streamlit preflight messages;
- no implicit Tavily fallback.

An integration smoke test starts the Docker service, waits for readiness, performs one general search and one image search, confirms JSON responses and normalized results, then verifies that the ledger reports zero incremental query cost.

## Acceptance

The implementation is accepted when:

- `docker compose up -d searxng` reaches a healthy state;
- `http://localhost:8080` opens locally;
- the application generates research sources and image candidates through SearXNG;
- no `SEARCH_API_KEY` is required;
- cost reports list SearXNG calls at zero incremental query cost;
- Tavily is called only when explicitly selected;
- existing tests and publishing/API functionality remain compatible.
