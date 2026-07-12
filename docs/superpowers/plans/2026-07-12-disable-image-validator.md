# Disable Image Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disconnect all vision-based item and pair validation from production video generation.

**Architecture:** Change only the production service factory. Construct `ReferenceImageService` without a validator, construct `VideoGenerationService` without an image validator, and remove the vision-provider dependency from preflight service construction while retaining deterministic media checks.

**Tech Stack:** Python, pytest

## Global Constraints

- Do not call the vision LLM during image acquisition or pair handling.
- Keep PNG normalization, background cleanup, minimum-size checks, and transparency checks.
- Keep image briefs and generated prompts.
- Add no source-code comments.

---

### Task 1: Disconnect production validation

**Files:**
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `src/app/services/reference_generation_factory.py`

**Interfaces:**
- Consumes: Existing provider factories and `build_reference_generation_service(settings)`.
- Produces: A `VideoGenerationService` whose `image_service.validator` and `image_validator` are both `None`.

- [ ] **Step 1: Write a failing factory test** that replaces provider factories with harmless objects, makes vision-provider access raise, builds the service, and asserts both validator slots are `None`.
- [ ] **Step 2: Run the focused test** with `python -m pytest tests/unit/test_reference_pipeline.py -k "production_pipeline_disables_image_validator" -v` and confirm it fails because the vision provider is still requested.
- [ ] **Step 3: Remove vision-provider construction and validator injection** from `build_reference_generation_service`; retain every deterministic image-processing dependency.
- [ ] **Step 4: Run the focused test**, then the complete suite, compilation, and `git diff --check`.
