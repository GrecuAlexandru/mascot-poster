# NVIDIA NIM Model Fallback Design

## Goal

Keep text generation available when an NVIDIA NIM model is temporarily unavailable by trying this ordered chain for every text completion:

1. `deepseek-ai/deepseek-v4-pro`
2. `minimaxai/minimax-m2.7`
3. `nvidia/nemotron-3-ultra-550b-a55b`

## Configuration

`NVIDIA_NIM_MODEL` remains the primary-model setting for backward compatibility and defaults to `deepseek-ai/deepseek-v4-pro`.

Add `NVIDIA_NIM_FALLBACK_MODELS` as a comma-separated ordered list. Its default is:

```text
minimaxai/minimax-m2.7,nvidia/nemotron-3-ultra-550b-a55b
```

The provider receives the primary model followed by the parsed fallback models. Empty entries and duplicate model identifiers are removed without changing the first-occurrence order.

## Request Behavior

Each completion call starts with the primary model and advances through the chain only when the current model is unavailable. Availability failures are:

- HTTP `404`
- HTTP `429`
- HTTP `5xx`
- request timeout
- transport/network failure

Each model is attempted once per completion call. This replaces the current same-model retry behavior for availability failures, avoiding repeated requests to a model that is already unavailable.

Other HTTP `4xx` responses fail immediately because they indicate authentication, authorization, or malformed-request problems that changing models is unlikely to solve.

Successful responses continue through the existing JSON parsing, schema validation, and repair behavior. A new repair request begins a fresh ordered completion chain.

If every model is unavailable, the provider raises one readable transient error listing the attempted models and retaining the final failure as its cause.

## Cost and Diagnostics

Every failed request is recorded against the model that was actually attempted. Successful usage is also attributed to the model returned by NVIDIA, falling back to the attempted model when the response omits it.

No API keys, response bodies containing credentials, or secret configuration values are logged.

## Testing

Provider tests will verify:

- the configured models are attempted in the required order;
- a successful fallback response is returned;
- `404`, `429`, `5xx`, timeout, and transport failures advance to the next model;
- non-retryable `4xx` responses fail immediately;
- exhausting the chain raises an error that lists every attempted model;
- request and cost attribution use the model for the individual attempt.

Configuration tests will verify the default model chain and propagation from settings into every NVIDIA-backed text role.

## Scope

This change affects only NVIDIA NIM text completions. OpenRouter proofreading, OpenRouter vision validation, image generation, job retry policy, and Telegram failure notifications remain unchanged.
