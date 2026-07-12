# Disable Image Validator Design

## Decision

The production reference-video pipeline will not instantiate or call the vision-based item or paired image validator. Generated and downloaded images will proceed after deterministic media processing only: readable image data, minimum dimensions, PNG normalization, solid-background removal, and usable transparency.

The text LLM will continue creating image briefs and prompts. Image generation retries remain limited to media failures; there will be no semantic confidence gate, pair rejection, validator-directed repair, or vision-model cost. Existing validator code remains available for isolated tests or future opt-in tooling but is disconnected from production generation.

## Verification

A factory-level regression test will prove that the production service has `image_service.validator is None` and `image_validator is None`, and that service construction never requests a vision provider. The full unit suite will verify the rest of the pipeline remains intact.
