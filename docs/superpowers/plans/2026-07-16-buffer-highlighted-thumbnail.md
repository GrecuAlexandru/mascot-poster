# Buffer Highlighted Thumbnail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Buffer select the real MP4 frame where the timed word „diferența” is actively highlighted in „Dar care e diferența?”.

**Architecture:** `CompiledVideoSpec` derives the target timestamp from the final word-level transcript. `ReferenceRenderService` persists the millisecond offset beside the MP4 in `thumbnail.json`, and `PublicationService` validates and forwards it to Buffer, falling back to the configured 2000 ms only when metadata is unavailable or invalid.

**Tech Stack:** Python 3.12, Pydantic, pytest, FFmpeg, Buffer GraphQL API, Docker Compose.

## Global Constraints

- The thumbnail must be an actual frame from the approved MP4.
- The selected time must be inside the timed word „diferența”, at its midpoint.
- Caption highlighting and thumbnail selection must use the same final transcript timing.
- No Buffer/R2 operation may occur before strict Telegram approval and MP4 hash validation.
- Existing working-tree changes outside the focused thumbnail timing path must remain untouched.

---

### Task 1: Derive the highlighted-word timestamp

**Files:**
- Modify: `src/app/domain/models.py`
- Test: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: `CompiledVideoSpec.transcript.words: list[TimedWord]`
- Produces: `CompiledVideoSpec.thumbnail_timestamp_seconds -> float`

- [ ] **Step 1: Add a failing phrase-timing test**

Create a transcript containing `Dar`, `care`, `e`, `diferența?` where the final word spans 1.1–1.5 seconds, then assert `thumbnail_timestamp_seconds == pytest.approx(1.3)`. Include punctuation and Romanian diacritics so normalization is exercised.

- [ ] **Step 2: Verify the focused test fails**

Run: `python -m pytest tests/unit/test_reference_pipeline.py::test_compiled_video_spec_selects_diferenta_word_for_thumbnail -q`

Expected: failure because `thumbnail_timestamp_seconds` does not exist.

- [ ] **Step 3: Implement normalized phrase matching**

Add a property that case-folds words, removes punctuation, folds diacritics for matching, finds the exact four-word sequence `dar care e diferenta`, and returns the midpoint of the final word. If no match exists, return the earlier of 2.0 seconds and the final valid video frame.

- [ ] **Step 4: Verify the focused test passes**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -q`

Expected: all reference-pipeline tests pass.

### Task 2: Persist renderer timing metadata

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/reference_render_service.py`
- Test: `tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: `CompiledVideoSpec.thumbnail_timestamp_seconds`
- Produces: `<job-dir>/thumbnail.json` with `thumbnail_offset_ms: int`; `RenderResult.thumbnail_timestamp_ms: int | None`

- [ ] **Step 1: Add a failing render-artifact test**

Render with the fake FFmpeg path and assert the resulting `thumbnail_timestamp_ms` matches the rounded derived timestamp and `thumbnail.json` contains the same non-negative integer.

- [ ] **Step 2: Verify the render test fails**

Run: `python -m pytest tests/unit/test_reference_renderer.py::test_reference_render_service_streams_dynamic_frames_and_writes_artifacts -q`

Expected: failure because the metadata artifact and typed field are absent.

- [ ] **Step 3: Write metadata beside the MP4**

Extend `RenderResult` with optional non-negative `thumbnail_timestamp_ms`. During rendering, round the derived seconds to milliseconds, write `{"thumbnail_offset_ms": value}` to `thumbnail.json`, and return the same value in `RenderResult`. Do not inject, append, or freeze any frame in `video.mp4`.

- [ ] **Step 4: Verify renderer coverage**

Run: `python -m pytest tests/unit/test_reference_renderer.py -q`

Expected: all renderer tests pass.

### Task 3: Forward the validated offset to Buffer

**Files:**
- Modify: `src/app/automation/publisher.py`
- Test: `tests/unit/test_publishing.py`

**Interfaces:**
- Consumes: `<approved-video-dir>/thumbnail.json`
- Produces: `BufferClient.create_video_post(..., thumbnail_offset_ms=<derived value>)`

- [ ] **Step 1: Add failing publication tests**

Assert a valid `thumbnail_offset_ms` is passed unchanged. Parameterize missing, malformed, non-integer, and negative metadata cases and assert they use the configured 2000 ms fallback.

- [ ] **Step 2: Verify publication tests fail**

Run: `python -m pytest tests/unit/test_publishing.py -q`

Expected: valid metadata is ignored before implementation.

- [ ] **Step 3: Implement safe metadata loading**

After approval/hash validation and before calling Buffer, read `thumbnail.json`, accept only an integer greater than or equal to zero, and otherwise use `self.thumbnail_offset_ms`. Pass the resolved value to `create_video_post`.

- [ ] **Step 4: Verify publication tests pass**

Run: `python -m pytest tests/unit/test_publishing.py -q`

Expected: all publishing tests pass.

### Task 4: Production verification and deployment

**Files:**
- Modify: `CURRENT_SETUP.md` and `CHANGELOG.md` in the sibling `homeserver` documentation repository after verification.

**Interfaces:**
- Consumes: rendered MP4, transcript, and `thumbnail.json`
- Produces: deployed worker/API behavior and visual acceptance evidence

- [ ] **Step 1: Run the complete suite**

Run: `python -m pytest -q`

Expected: zero failures; the existing Starlette deprecation warning is acceptable.

- [ ] **Step 2: Commit and push only focused implementation files**

Stage the domain timing property, render metadata, publisher loader, and their focused tests. Preserve unrelated working-tree changes. Commit to `main` and push.

- [ ] **Step 3: Pull, rebuild, and recreate affected containers**

On VM 100, pull `main`, rebuild `api` and `worker`, and force-recreate only those services. Verify zero restarts and no recent exceptions.

- [ ] **Step 4: Produce metadata for the current review video**

Rerender the current approved-candidate job from existing checkpoints so the final MP4 and its hash remain subject to a fresh Telegram approval. Do not publish it automatically.

- [ ] **Step 5: Extract and inspect the real frame**

Read the generated offset, extract that exact MP4 frame with the container’s FFmpeg, and visually confirm the caption displays „diferența” in the active highlight color. If it does not, stop before Buffer submission and correct the timing selection.

- [ ] **Step 6: Record verified infrastructure state**

Update the home-server source-of-truth documentation with the deployed commit, test count, visual result, and any remaining Buffer acceptance step; commit only those documentation hunks.
