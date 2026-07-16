# Single-Line CTA Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `LIKE · SHARE · FOLLOW` as one centered row inside the existing CTA safe width.

**Architecture:** Keep normal speech-bubble wrapping unchanged, but give the normalized production CTA a one-line layout path. That path measures the complete text and decreases the existing CTA font until it fits within 760 pixels, then the existing card builder derives a one-line height from the returned layout.

**Tech Stack:** Python 3.12, Pillow, pytest, Docker Compose.

## Global Constraints

- Keep the exact visible text `LIKE · SHARE · FOLLOW`.
- Keep all text inside the existing 760-pixel inner safe width.
- Keep the banner centered and readable.
- Do not change CTA timing, colors, animation, karaoke captions, thumbnails, or publishing.
- Preserve unrelated working-tree changes through selective staging.

---

### Task 1: Enforce a one-line production CTA layout

**Files:**
- Modify: `src/app/rendering/reference_renderer.py`
- Test: `tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: `ReferenceRenderer._cta_display_text("Like, share, follow")`
- Produces: `ReferenceRenderer._bubble_lines(...) -> (font, ["LIKE · SHARE · FOLLOW"])`

- [ ] **Step 1: Write the failing layout test**

Assert the production CTA returns exactly one line and `measure_text(line, font)[0] <= 760`. Assert the generated card height equals the single-line text height plus existing padding and margins.

- [ ] **Step 2: Run the focused test**

Run: `python -m pytest tests/unit/test_reference_renderer.py::test_reference_renderer_uses_a_tail_free_cta_card -q`

Expected before the fix: failure because the deployed wrapping path can split the CTA.

- [ ] **Step 3: Implement single-line shrinking**

Add a helper that loads the CTA font from the preferred size downward and returns the first font for which the complete display text fits 760 pixels. Use that helper for the normalized production CTA only; leave explicit line breaks and generic speech-bubble wrapping unchanged.

- [ ] **Step 4: Verify renderer tests**

Run: `python -m pytest tests/unit/test_reference_renderer.py -q`

Expected: all renderer tests pass.

### Task 2: Deploy and visually verify

**Files:**
- Modify after verification: `CURRENT_SETUP.md` and `CHANGELOG.md` in the sibling `homeserver` repository.

**Interfaces:**
- Consumes: current compiled fridge/freezer checkpoint.
- Produces: rerendered review MP4 with a one-row CTA and fresh Telegram approval hash.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`

Expected: zero failures; the existing Starlette deprecation warning is acceptable.

- [ ] **Step 2: Commit and push focused files**

Selectively stage the CTA renderer hunk and focused test only, commit to `main`, and push without staging unrelated thumbnail/font work.

- [ ] **Step 3: Deploy the worker**

Pull `main` on VM 100, rebuild the worker image, and recreate only the worker. Verify it runs with zero restarts.

- [ ] **Step 4: Rerender from existing checkpoints**

Invalidate only render and quality for the current review candidate, clear its prior approval/hash, and rerender without rerunning topic, research, images, script, or TTS.

- [ ] **Step 5: Inspect a real closing frame**

Extract a frame during the closing CTA and visually confirm one centered row inside the safe bounds. Stop and correct the implementation if it wraps.

- [ ] **Step 6: Record verified state**

Update the home-server source-of-truth documentation with the deployed commit, test evidence, visual verification, and remaining Telegram/Buffer acceptance state; commit only those documentation hunks.
