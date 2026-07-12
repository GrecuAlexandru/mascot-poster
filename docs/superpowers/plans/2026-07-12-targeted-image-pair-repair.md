# Targeted Image Pair Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perform at most one validator-directed image repair, preserve acceptable sides, guide Gemini with reference images and richer instructions, and continue after residual cosmetic mismatches.

**Architecture:** Extend pair validation with structured repair classification, extend the OpenRouter image provider with reference-image inputs, and replace the two-round two-sided repair loop with a one-shot targeted repair coordinator. Fatal semantic/content failures remain blocking after repair; composition and style differences become recorded warnings.

**Tech Stack:** Python, Pydantic, Pillow, httpx, OpenRouter Image API, pytest

## Global Constraints

- Perform exactly one repair round and never enter another generation loop.
- Preserve acceptable images and regenerate only the side selected by validation.
- Use `input_references` with base64 data URLs for one-sided repair.
- Use one wide image-generation call and deterministic splitting when both sides require repair.
- Keep wrong identity, unwanted text, prohibited content, unusable background, and non-photorealistic imagery fatal.
- Treat residual scale, position, crop, lighting, shadow, and color differences as warnings after repair.
- Never reject a pair merely because compared products have different colors.
- Add no source-code comments.

---

### Task 1: Structured repair classification

**Files:**
- Modify: `src/app/services/reference_image_validator.py`
- Modify: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `ImageValidationResult.repair_side`, `repair_instructions`, `fatal_reasons`, `warning_reasons`, `has_fatal_issues`, and `needs_repair`.
- Consumes: Existing Pydantic structured vision completion.

- [ ] **Step 1: Write failing tests** asserting cosmetic mismatches are warnings, color contrast cannot be fatal, unwanted text remains fatal, and repair-side instructions are preserved.
- [ ] **Step 2: Run focused tests** with `python -m pytest tests/unit/test_reference_assets.py -k "repair_classification or color_difference" -v` and confirm assertion failures.
- [ ] **Step 3: Add typed repair fields and derived policy properties** to `ImageValidationResult` and update the pair-inspector prompt to classify each issue and forbid color-only rejection.
- [ ] **Step 4: Re-run the focused tests** and confirm they pass.

### Task 2: Reference-guided image generation

**Files:**
- Modify: `src/app/providers/images/base.py`
- Modify: `src/app/providers/images/openrouter_provider.py`
- Modify: `src/app/services/reference_image_service.py`
- Modify: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `generate(..., input_references: Optional[list[Path]] = None)` and `ReferenceImageService.acquire(..., input_references, repair_instructions, generated_attempt_limit)`.
- Consumes: OpenRouter `input_references` objects shaped as `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`.

- [ ] **Step 1: Write failing provider tests** asserting reference images are encoded as data URLs, affect the cache key, and are omitted for ordinary generation.
- [ ] **Step 2: Write failing prompt/service tests** asserting detailed composition matching, strict blank-surface language, identity-preservation language, and one generated attempt.
- [ ] **Step 3: Run focused tests** and confirm failures come from missing reference/prompt interfaces.
- [ ] **Step 4: Implement reference encoding and cache identity** in the OpenRouter provider and thread targeted repair inputs through `ReferenceImageService`.
- [ ] **Step 5: Re-run focused tests** and confirm they pass.

### Task 3: One-shot repair coordinator and final policy

**Files:**
- Modify: `src/app/services/video_generation_service.py`
- Modify: `src/app/services/reference_quality_service.py`
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: `ImageValidationResult.repair_side`, `repair_instructions`, `has_fatal_issues`, and reference-capable image acquisition.
- Produces: one-sided preservation, one wide-call two-sided repair, final warnings in provenance/quality data, and no retry loop.

- [ ] **Step 1: Write failing orchestration tests** for left-only, right-only, both-sided, no-repair, exactly-one-round, fatal final failure, and cosmetic final continuation.
- [ ] **Step 2: Run focused orchestration tests** and confirm the current two-round regeneration loop violates call counts and preservation.
- [ ] **Step 3: Replace `_repair_pair_until_accepted`** with a one-shot coordinator, add wide-image splitting for `both`, and base final failure only on `has_fatal_issues`.
- [ ] **Step 4: Store initial validation, final validation, repair metadata, and warnings** in provenance and quality output.
- [ ] **Step 5: Run focused tests**, then `python -m pytest tests/ -q`, `python -m compileall -q src streamlit_app.py`, and `git diff --check`.
