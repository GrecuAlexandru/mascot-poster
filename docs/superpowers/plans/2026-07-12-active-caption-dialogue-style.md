# Active Caption and Dialogue Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render one consistent background only behind the active caption word, retain balanced base product sizing with focus zoom, and guide Romanian scripts toward the supplied conversational style with a short `Pe scurt,` verdict.

**Architecture:** Keep visual behavior inside `ReferenceRenderer` and writing guidance inside `ReferenceScriptService`. Reuse the existing caption timing, compact layout, product-pair fitter, and deterministic bookend enforcement; only narrow the card drawing condition and strengthen the prompt contract.

**Tech Stack:** Python 3, Pillow, Pydantic, pytest

## Global Constraints

- Do not remove the existing 128% active-product focus zoom.
- Use `#E87560` as the only active-word caption background.
- The conclusion contains 4-12 words after `Pe scurt,` or `In short,`.
- Do not add source-code comments.
- Preserve unrelated working-tree changes.

---

### Task 1: Active-only caption card

**Files:**
- Modify: `tests/unit/test_reference_renderer.py`
- Modify: `src/app/rendering/reference_renderer.py`

**Interfaces:**
- Consumes: `ReferenceRenderer._draw_caption(draw: ImageDraw.ImageDraw, cue: CaptionCue | None) -> None`
- Produces: `ReferenceRenderer.caption_highlight_color: tuple[int, int, int]`

- [ ] **Step 1: Replace the colored-card regression test with an active-only test**

Create a two-word cue whose first word is active. Assert a pixel in the first word's padding equals `(232, 117, 96, 255)` and the equivalent pixel around the second word remains white.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_reference_renderer.py::test_reference_renderer_draws_one_fixed_card_behind_only_the_active_caption_word -v`

Expected: FAIL because the inactive word still receives its own colored card and `caption_highlight_color` does not exist.

- [ ] **Step 3: Implement the minimal renderer change**

Replace `caption_word_colors` with `caption_highlight_color = (232, 117, 96)`. In `_draw_caption`, calculate `active` before drawing the card and call `draw.rounded_rectangle(...)` only when `active` is true. Keep current active/inactive text colors, outline, shadow, padding, and layout.

- [ ] **Step 4: Run renderer tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_renderer.py -v`

Expected: all tests pass, including equal neutral product extent and `product_scale_at(..., Focus.LEFT) == 1.28`.

### Task 2: Conversational script prompt and short verdict

**Files:**
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `src/app/services/reference_script_service.py`

**Interfaces:**
- Consumes: `ReferenceScriptService.generate(...) -> ReferenceScriptPackage`
- Produces: a prompt contract containing the supplied Romanian example and a 4-12-word verdict requirement

- [ ] **Step 1: Add failing prompt-contract assertions**

Extend the existing script-service test to assert the user prompt includes `modern`, `ironic`, `4-12`, `zahăr vanilat`, `rimeicul`, and an instruction not to reuse facts from the example.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py::test_reference_script_service_uses_structured_output_and_balanced_prompt -v`

Expected: FAIL because the current prompt has none of the new style example or short-verdict constraints.

- [ ] **Step 3: Implement the prompt guidance**

Add a Romanian reference-transcript constant and prompt instructions that allow conversational modern language and light irony, prohibit forced slang and unsupported jokes, label the transcript as style-only, and require one short 4-12-word verdict after the summary prefix. Keep the exact opening and separate sign-off behavior.

- [ ] **Step 4: Run script-generation tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_generation.py -v`

Expected: all tests pass.

### Task 3: Regression verification

**Files:**
- Verify: `src/app/rendering/reference_renderer.py`
- Verify: `src/app/services/reference_script_service.py`
- Verify: `tests/unit/test_reference_renderer.py`
- Verify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: completed Tasks 1 and 2
- Produces: verified project behavior

- [ ] **Step 1: Run all unit tests**

Run: `python -m pytest tests/unit/ -v`

Expected: zero failures.

- [ ] **Step 2: Inspect the final diff**

Run: `git diff --check` and `git diff -- src/app/rendering/reference_renderer.py src/app/services/reference_script_service.py tests/unit/test_reference_renderer.py tests/unit/test_reference_generation.py`

Expected: no whitespace errors; only the approved renderer, prompt, and test changes appear among pre-existing edits.

