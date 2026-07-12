# Dual Text LLM and Image Model Design

## Goal

Allow one boolean environment switch to route every text-only generation stage through either the existing OpenRouter Haiku configuration or NVIDIA NIM Qwen3.5-397B-A17B, while retaining OpenRouter for vision and image generation and changing the image model to `google/gemini-3.1-flash-lite-image`.

## Provider boundaries

`USE_NVIDIA_NIM_TEXT_LLM=false` selects the existing OpenRouter providers and their role-specific model variables. `USE_NVIDIA_NIM_TEXT_LLM=true` selects NVIDIA NIM for topic generation, research synthesis, script generation, direction, image briefs, and fact checking. Vision validation continues to use `OPENROUTER_VISION_MODEL` and `OPENROUTER_API_KEY`.

NVIDIA configuration uses `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1`, and `NVIDIA_NIM_MODEL=qwen/qwen3.5-397b-a17b`. Selected-provider configuration errors fail early with a clear message. The NIM provider implements the existing `LLMProvider` interface, disables thinking, requests JSON through the prompt, validates with Pydantic, and uses the existing repair-loop behavior without sending OpenRouter-specific routing or JSON-schema fields.

## Image generation

The default `OPENROUTER_IMAGE_MODEL` becomes `google/gemini-3.1-flash-lite-image`. The configured slug is passed through exactly. The OpenRouter Image API remains the transport and image generation remains independently configurable from the text-provider switch.

## Verification

Unit tests cover default configuration, NVIDIA selection for every text role, OpenRouter selection when disabled, missing-key behavior, NIM request shape and structured repair, and the exact image-model slug. The complete test suite verifies that existing rendering and pipeline behavior remains intact.
