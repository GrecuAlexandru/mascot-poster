# Source-Aware Image Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use validated web images only when a comparison depends on a real-world visual identity, while generating ordinary-object images directly without semantic validation.

**Architecture:** The image brief gains explicit source and text-language decisions made by the existing text LLM. The reference image service uses those decisions to either validate up to three search candidates or generate directly; generated images never enter the semantic or paired validation paths.

**Tech Stack:** Python, Pydantic, httpx providers, pytest.

## Global Constraints

- Keep all external services behind existing provider interfaces.
- AI image prompts are written in English.
- AI-rendered intrinsic text is Romanian only when the brief requests Romanian; English only when it requests English; otherwise no readable text is allowed.
- Search candidates are attempted at most three times and must pass media and vision validation.
- Generated images are never semantically or pair validated.
- Preserve existing unrelated working-tree changes.

---

### Task 1: Extend the image brief contract

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/reference_image_brief_service.py`
- Test: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `ProductImageBrief.requires_real_reference: bool` and `ProductImageBrief.image_text_language: Literal["romanian", "english", "none"]`.

- [ ] **Step 1: Write failing model-default and brief-prompt tests**

```python
brief = ProductImageBrief(item="Frigider", exact_subject="refrigerator")
assert brief.requires_real_reference is False
assert brief.image_text_language == "none"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/unit/test_reference_assets.py -v`
Expected: failure because the new fields do not exist.

- [ ] **Step 3: Add the fields and LLM classification instructions**

```python
requires_real_reference: bool = False
image_text_language: Literal["romanian", "english", "none"] = "none"
```

The brief prompt must set `requires_real_reference` for brands, named product models, vehicle makes/models, app/OS interfaces, and other subjects where faithful real-world appearance is necessary; it must set it false for generic physical objects. It must set the text language only for text intrinsic to the requested subject.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/unit/test_reference_assets.py -v`
Expected: PASS.

### Task 2: Route acquisition by brief source policy

**Files:**
- Modify: `src/app/services/reference_image_service.py`
- Test: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Consumes: `ProductImageBrief.requires_real_reference` and `ProductImageBrief.image_text_language`.
- Produces: `ReferenceImageService.acquire(...)` that skips search for generic objects, considers at most three real-image candidates for identity-critical objects, and falls back to unvalidated generation.

- [ ] **Step 1: Write failing routing tests**

```python
normal = ProductImageBrief(item="Frigider", exact_subject="refrigerator")
service.acquire("Frigider", brief=normal)
assert search.calls == []

brand = ProductImageBrief(item="iPhone", exact_subject="Apple iPhone", requires_real_reference=True)
service.acquire("iPhone", brief=brand)
assert validator.calls == 3
assert generator.calls == 1
```

- [ ] **Step 2: Run routing tests and verify they fail**

Run: `python -m pytest tests/unit/test_reference_assets.py -k "direct_generation or search_candidates" -v`
Expected: FAIL because acquisition always searches and accepts five candidates today.

- [ ] **Step 3: Implement source-aware routing**

Use the search provider only when `requires_real_reference` is true, slice candidates to `max_candidates=3`, and call the vision validator only for those downloaded candidates. When no candidate is accepted, call the generated provider; do not call `_validate` for generated assets.

- [ ] **Step 4: Run routing tests and verify they pass**

Run: `python -m pytest tests/unit/test_reference_assets.py -k "direct_generation or search_candidates" -v`
Expected: PASS.

### Task 3: Encode text language and identity-aware validation rules

**Files:**
- Modify: `src/app/services/reference_image_service.py`
- Modify: `src/app/services/reference_image_validator.py`
- Test: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `build_generation_prompt(...)` language-specific text constraints and real-reference validator guidance that permits identity-defining text but rejects unrelated overlays.

- [ ] **Step 1: Write failing prompt and validator-guidance tests**

```python
assert "Romanian" in build_generation_prompt(..., brief=romanian_brief)
assert "English" in build_generation_prompt(..., brief=english_brief)
assert "no readable text" in build_generation_prompt(..., brief=textless_brief).lower()
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `python -m pytest tests/unit/test_reference_assets.py -k "generation_prompt or identity" -v`
Expected: FAIL because language constraints and identity-text exception are absent.

- [ ] **Step 3: Implement prompt and validator guidance**

Add English-language prompt clauses for `romanian`, `english`, and `none`. In the item-validation prompt, permit only expected logos, model names, and normal interface text when `requires_real_reference` is true; retain rejection of unrelated watermarks, headers, and advertising text.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/unit/test_reference_assets.py -k "generation_prompt or identity" -v`
Expected: PASS.

### Task 4: Wire production validation to search-only use

**Files:**
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Produces: production `ReferenceImageService` with a search-candidate vision validator and production `VideoGenerationService.image_validator is None`.

- [ ] **Step 1: Update the failing factory test**

```python
assert isinstance(service.image_service.validator, ReferenceImageValidator)
assert service.image_validator is None
```

- [ ] **Step 2: Run the factory test and verify it fails**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "production_pipeline" -v`
Expected: FAIL because the factory currently installs no image validator.

- [ ] **Step 3: Restore a vision provider only for search candidate validation**

Build `ReferenceImageValidator(get_vision_llm_provider())` for `ReferenceImageService`, set `max_candidates=3`, and keep the video-generation pair validator unset.

- [ ] **Step 4: Run the factory test and verify it passes**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "production_pipeline" -v`
Expected: PASS.

### Task 5: Verify the end-to-end change

**Files:**
- Test: `tests/unit/`

- [ ] **Step 1: Run focused reference tests**

Run: `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py -v`
Expected: PASS.

- [ ] **Step 2: Run the full unit suite and static syntax checks**

Run: `python -m pytest tests/ -v; python -m compileall -q src; git diff --check`
Expected: all tests pass, compilation exits 0, and no whitespace errors are reported.
