# Cut-Paper Captions and Memory Device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every caption word as deterministic cut-paper typography and require one grounded, repeatable memory-device line in every generated reference script.

**Architecture:** Extend the Pydantic script contract with a validated `MemoryDevice`, then preserve it through generation, proofing, verification, checkpointing, TTS, and final quality checks. Keep word timing unchanged while tightening timeline chunking to one-to-three words, and isolate deterministic card geometry/layout in the reference renderer.

**Tech Stack:** Python 3.14, Pydantic, Pillow, pytest.

## Global Constraints

- Add no 27–34-second enforcement, rejection rule, or duration quality gate.
- Change the default requested duration from 25 seconds to 30 seconds while preserving explicit 20-, 25-, and 60-second requests.
- Preserve exact TTS word timing and active-word sequence.
- Use only coral `#E87560`, mustard `#F2C14E`, and mint `#78C6A3` for caption cards.
- Use dark caption text `#241F1A` without a heavy white outline.
- Keep all geometry deterministic across processes and frames.
- Preserve existing verified claims and do not add facts through memory-device wording.

---

### Task 1: Add the structured memory-device contract

**Files:**
- Modify: `src/app/domain/enums.py`
- Modify: `src/app/domain/models.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Produces: `MemoryDeviceKind`, `MemoryDevice(kind, line, beat_id)`, and required `ReferenceScriptPackage.memory_device`.
- Consumes: existing `NarrationBeat` IDs and text.

- [ ] **Step 1: Write failing model tests**

Add tests proving all four kinds validate and proving rejection for a 5-word line, a 21-word line, a missing beat, a hook/closing beat, and a line not present as a complete sentence in the referenced beat.

- [ ] **Step 2: Run the model tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "memory_device" -q`

Expected: collection or assertion failure because the contract does not exist.

- [ ] **Step 3: Implement the minimal contract**

Add:

```python
class MemoryDeviceKind(str, Enum):
    ANALOGY = "analogy"
    SURPRISING_CORRECTION = "surprising_correction"
    HUMOROUS_CONTRAST = "humorous_contrast"
    REPEATABLE_SENTENCE = "repeatable_sentence"


class MemoryDevice(BaseModel):
    kind: MemoryDeviceKind
    line: str
    beat_id: str
```

Normalize whitespace, enforce 6–20 words, resolve exactly one non-hook beat, and require the line as a complete sentence inside that beat. Update all test fixtures constructing `ReferenceScriptPackage` with a valid memory-device beat.

- [ ] **Step 4: Run model and existing reference script tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -q`

Expected: PASS.

### Task 2: Require and preserve the memorable line during generation and proofing

**Files:**
- Modify: `src/app/services/reference_script_service.py`
- Modify: `src/app/services/reference_proofreader.py`
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `tests/unit/test_reference_proofreader.py`

**Interfaces:**
- Consumes: required `ReferenceScriptPackage.memory_device` from Task 1.
- Produces: script prompts that require exactly one grounded memory device and proofread scripts whose beat text and `memory_device.line` remain identical.

- [ ] **Step 1: Write failing prompt and proofreader tests**

Assert that the generation prompt names all four kinds, requires exactly one dedicated beat, restricts the line to supplied facts, includes the refrigerator/freezer sentence as structure-only guidance, and identifies a roughly 30-second default as guidance rather than a gate. Add a proofreader test where both the beat and memory line receive the same Romanian correction.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_reference_proofreader.py -k "memory or default_duration" -q`

Expected: assertion failures for missing prompt/proofreader behavior.

- [ ] **Step 3: Implement generation and proofing consistency**

Add explicit prompt rules for one non-quantitative memory device, its four kinds, exact beat inclusion, claim linkage, and no unsupported claims. Update the complete JSON example. Ensure bookend normalization retains the memory-device object unchanged. Extend the proofreader prompt to treat the selected beat and `memory_device.line` as one consistency unit; retain the existing original-script fallback when validation fails.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_reference_proofreader.py -q`

Expected: PASS.

### Task 3: Change default pacing guidance without adding enforcement

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/reference_script_service.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Produces: `GenerationRequest().target_duration_seconds == 30` and unchanged explicit duration validation.
- Consumes: existing word-budget calculation `target_duration_seconds * 2`.

- [ ] **Step 1: Write failing duration-contract tests**

Assert default 30, explicit 20/25/60 acceptance, a 60-word default budget, a 50-word explicit 25-second budget, and unchanged `_duration_is_acceptable` results at 20 and 60. Do not add any assertion requiring 27–34 seconds.

- [ ] **Step 2: Run duration tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -k "duration or word_budget" -q`

Expected: the default-duration assertion fails with 25.

- [ ] **Step 3: Change only the default and prompt wording**

Set `GenerationRequest.target_duration_seconds` default to 30. Describe the requested value as approximate pacing guidance in the script prompt. Leave `_duration_is_acceptable`, request bounds, TTS repair behavior, and final quality duration logic otherwise unchanged.

- [ ] **Step 4: Run duration tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -k "duration or word_budget" -q`

Expected: PASS.

### Task 4: Compile one-to-three-word caption chunks

**Files:**
- Modify: `src/app/services/timeline_compiler.py`
- Modify: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: `TimedTranscript.words` and the existing pause/punctuation boundaries.
- Produces: `CaptionCue.words` chunks with at most 3 words and 24 visible characters while retaining one cue per active word.

- [ ] **Step 1: Write failing chunk-boundary tests**

Cover one-, two-, and three-word chunks, a forced split before word four, a punctuation split, a split above 24 characters, and a split after a pause over 300 milliseconds. Assert the active-word sequence exactly equals narration.

- [ ] **Step 2: Run timeline tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "caption" -q`

Expected: the existing compiler still emits a four-word chunk or permits 26 characters.

- [ ] **Step 3: Tighten compiler defaults**

Set `max_caption_words=3` and `max_caption_characters=24`, preserving the existing strict `> 0.3` pause boundary and punctuation behavior.

- [ ] **Step 4: Run timeline tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "caption" -q`

Expected: PASS.

### Task 5: Render deterministic cut-paper word cards

**Files:**
- Modify: `src/app/rendering/reference_renderer.py`
- Modify: `templates/reference_v1.json`
- Modify: `tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: one-to-three-word `CaptionCue` values from Task 4.
- Produces: deterministic `caption_card_style(word, index)` and a card-per-word caption layer using the approved palette and active emphasis.

- [ ] **Step 1: Write failing style and geometry tests**

Assert the exact three RGB colors, dark text, stable ±1/±2-degree rotation, corner offsets bounded to six pixels, identical style on repeated calls, 1.06 active scale, six-pixel lift, no white glyph outline, and all rendered card pixels inside the caption region for long Romanian words.

- [ ] **Step 2: Run renderer tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption" -q`

Expected: assertion failures because only the active word currently receives one rounded card.

- [ ] **Step 3: Implement card layout and drawing**

Use `hashlib.sha256` over normalized word text and position for stable rotation/corners. Measure a shared font starting at 118 pixels, generate a transparent layer per word with an irregular polygon, render dark flat text, apply 1.06 scale and a six-pixel lift to the active layer, rotate with bicubic resampling, and center the complete measured group within the caption region. Keep at most two rows and shrink the shared font before clipping.

- [ ] **Step 4: Run renderer tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_renderer.py -q`

Expected: PASS.

### Task 6: Verify memory-device survival in final artifacts

**Files:**
- Modify: `src/app/services/reference_quality_service.py`
- Modify: `src/app/services/video_generation_service.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: compiled script checkpoint and timed transcript.
- Produces: deterministic quality problem when the exact structured memory-device words do not survive into narration.

- [ ] **Step 1: Write failing quality and serialization tests**

Assert memory-device JSON survives checkpoint serialization and that quality accepts an exact normalized spoken subsequence but rejects a missing or changed line.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -k "memory_device" -q`

Expected: missing quality method or missing compiled metadata.

- [ ] **Step 3: Carry memory-device metadata into compiled specs and validate it**

Add `memory_device` to `CompiledVideoSpec`, pass it during compilation, and compare its normalized token sequence against `TimedTranscript.words` in final quality. Return `Memorable line is missing from compiled narration` when absent. Do not add semantic style classification or duration enforcement.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -k "memory_device" -q`

Expected: PASS.

### Task 7: Full verification

**Files:**
- Verify all modified production, template, and test files.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: repository-wide evidence that the integrated behavior is stable.

- [ ] **Step 1: Run focused feature suites**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py tests/unit/test_reference_proofreader.py tests/unit/test_reference_renderer.py -q`

Expected: PASS.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest tests/ -v`

Expected: PASS with zero failures.

- [ ] **Step 3: Validate the working-tree patch**

Run: `git diff --check`

Expected: exit code 0 with no whitespace errors. Inspect `git status --short` and preserve unrelated pre-existing edits.
