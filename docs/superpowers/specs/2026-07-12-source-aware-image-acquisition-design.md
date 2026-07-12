# Source-Aware Image Acquisition Design

## Goal

Choose image acquisition per comparison side so real-world visual identities use validated web images while ordinary objects use AI generation directly.

## Brief classification

`ProductImageBrief` gains:

- `requires_real_reference`: true only when the requested item depends on its real visual identity, including brands, named products or models, distinctive vehicles, operating systems, websites, apps, and recognizable interfaces.
- `image_text_language`: `romanian`, `english`, or `none`, describing intrinsic readable text required in an AI-generated image.

The image-brief LLM decides both fields per side. It must use `none` for ordinary objects, Romanian only for genuinely Romanian-localized text, and English for all other intrinsic text.

## Acquisition policy

For `requires_real_reference=false`, skip web search and generate the image immediately. For `requires_real_reference=true`, search and download at most three candidates. Each candidate must pass deterministic media checks and vision item validation. Expected brand marks, model labels, and normal interface text needed to establish real identity are allowed; unrelated text, a wrong identity, prohibited content, or unusable imagery fail.

If no real candidate passes after three attempts, generate an AI fallback. Generated images are never sent to the vision validator or paired validator.

## Generation prompts

All generation instructions are English. The prompt explicitly prohibits decorative text. When intrinsic text is required, it requires the brief's selected language: Romanian for Romanian-localized real-world text, otherwise English. The prompt otherwise requires no readable text.

## Production wiring

The production factory restores a vision provider only for `ReferenceImageService` search-candidate validation. `VideoGenerationService.image_validator` remains `None`, so generated and paired images never have a confidence, semantic, or composition gate.

## Tests

Tests cover brief fields, direct generation for ordinary objects, three-candidate validated search for real identity, failed-search fallback generation without validation, expected brand text acceptance, English/Romanian/no-text prompt rules, and factory wiring.
