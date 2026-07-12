# Caption, Outro, and CTA Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten and vertically balance captions, slow only the Pufăilă closing beat, and render a bold high-contrast CTA card.

**Architecture:** `ReferenceRenderer` remains responsible for caption and CTA drawing, with reusable geometry derived from Pillow text bounding boxes. `BeatTTSService` derives immutable per-beat `TTSSettings`, overriding only the closing speed while leaving the provider interface and regular narration settings unchanged.

**Tech Stack:** Python 3.14, Pillow, Pydantic, ElevenLabs-compatible TTS provider interface, pytest.

## Global Constraints

- Keep regular narration speed at `1.05` and closing speed at `0.88`.
- Keep canonical closing text exactly `Vă pupă Pufăilă!` and retain the configured closing pause.
- Keep caption colors, grouping, font size, rows, timing, and configured region unchanged.
- Display the CTA as `LIKE · SHARE · FOLLOW` on a dark rounded card with a thick yellow border, white heavy text, and a stronger soft shadow.
- Add no source-code comments and preserve provider interfaces.

---

### Task 1: Compact and vertically balance captions

**Files:**
- Modify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_renderer.py`
- Modify: `C:/Users/Alex/Desktop/mascot-poster/src/app/rendering/reference_renderer.py`

**Interfaces:**
- Consumes: `PIL.ImageDraw.textbbox`, `ReferenceRenderer._caption_layout(words, region)`.
- Produces: `ReferenceRenderer.caption_word_gap_ratio = 0.40` and active-card bounds centered on the measured glyph box.

- [ ] **Step 1: Write failing caption tests**

Update the caption-style assertion to require `0.40`. Replace baseline-derived card sampling with a test that obtains `textbbox((x, y), word, font, stroke_width=stroke)` and asserts the coral card extends by the same `padding_y` above and below that box, within one pixel.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption" -v`

Expected: FAIL because the ratio remains `0.52` and the current rectangle is based on `y` plus `measure_text("Ag")` rather than the active word's bounding box.

- [ ] **Step 3: Implement caption geometry**

Set `caption_word_gap_ratio = 0.40`. In `_draw_caption`, calculate the active word's bounding box using the same position, font, and stroke width used to draw it, then expand that box by the existing horizontal and vertical padding when drawing the rounded rectangle.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption" -v`

Expected: all selected caption tests PASS.

### Task 2: Render the bold CTA card

**Files:**
- Modify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_renderer.py`
- Modify: `C:/Users/Alex/Desktop/mascot-poster/src/app/rendering/reference_renderer.py`

**Interfaces:**
- Consumes: `_build_speech_bubble(text: str) -> tuple[Image.Image, int]`.
- Produces: `_cta_display_text(text: str) -> str` and a tail-free dark/yellow CTA card.

- [ ] **Step 1: Write failing CTA tests**

Add assertions that `_cta_display_text("Like, share, follow")` returns `LIKE · SHARE · FOLLOW`, the card center is the dark fill color, a pixel on the body border is yellow, visible text pixels are white, and `anchor_y == card.height`.

- [ ] **Step 2: Run the CTA tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "cta" -v`

Expected: FAIL because `_cta_display_text` does not exist and the card is white with a dark border.

- [ ] **Step 3: Implement the bold CTA**

Normalize comma-separated CTA words to uppercase joined with ` · `. Use the normalized text for layout and cache identity. Draw a `(24, 25, 30, 255)` body, a `(255, 196, 61, 255)` border at width `7`, white text, increased font weight through the existing bold-capable font path where available, and a darker, more opaque blurred shadow. Remove the prior amber underline.

- [ ] **Step 4: Run the CTA tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "cta" -v`

Expected: all selected CTA tests PASS.

### Task 3: Slow only the closing beat

**Files:**
- Modify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_pipeline.py`
- Modify: `C:/Users/Alex/Desktop/mascot-poster/src/app/services/beat_tts_service.py`

**Interfaces:**
- Consumes: `TTSSettings.model_copy(update={"speed": 0.88})` and narration beat id `closing`.
- Produces: `BeatTTSService._settings_for_beat(settings: TTSSettings, beat_id: str) -> TTSSettings`.

- [ ] **Step 1: Write a failing per-beat settings test**

Extend the fake provider call capture to include `settings`. Invoke synthesis with `TTSSettings(speed=1.05)` and assert the captured speeds are `[1.05, 1.05, 0.88]`, the closing text remains unchanged, and its pause remains `500` milliseconds.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py::test_beat_tts_offsets_words_and_inserts_exact_pauses -v`

Expected: FAIL because all three provider calls currently receive speed `1.05`.

- [ ] **Step 3: Implement closing-only settings**

Derive `beat_settings = self._settings_for_beat(settings, beat.id)` in the loop, pass it to the provider, and use its model id for the matching cost event. Return the original settings for non-closing beats and `settings.model_copy(update={"speed": 0.88})` for `closing`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py::test_beat_tts_offsets_words_and_inserts_exact_pauses -v`

Expected: PASS with captured speeds `[1.05, 1.05, 0.88]`.

### Task 4: Integrated verification

**Files:**
- Verify: `C:/Users/Alex/Desktop/mascot-poster/src/app/rendering/reference_renderer.py`
- Verify: `C:/Users/Alex/Desktop/mascot-poster/src/app/services/beat_tts_service.py`
- Verify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_renderer.py`
- Verify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: completed renderer and TTS behavior.
- Produces: test evidence and representative caption/CTA frame artifacts.

- [ ] **Step 1: Run focused test files**

Run: `python -m pytest tests/unit/test_reference_renderer.py tests/unit/test_reference_pipeline.py -v`

Expected: all tests PASS.

- [ ] **Step 2: Run the full unit suite**

Run: `python -m pytest tests/ -v`

Expected: all tests PASS with zero failures.

- [ ] **Step 3: Render representative frames**

Use the renderer test fixtures to save one active two-line caption frame and one CTA frame under a temporary verification directory. Inspect both images for compact spacing, balanced active-card padding, legibility, CTA contrast, clipping, and safe-zone placement.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check` and `git diff -- src/app/rendering/reference_renderer.py src/app/services/beat_tts_service.py tests/unit/test_reference_renderer.py tests/unit/test_reference_pipeline.py`

Expected: no whitespace errors and only approved behavior changes.
