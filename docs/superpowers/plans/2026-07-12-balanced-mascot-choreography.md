# Balanced Mascot Choreography Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent comparison videos from getting stuck on one mascot pose and improve subtitle spacing and colored row cards.

**Architecture:** Keep the LLM direction plan as a creative input, then deterministically enforce left/right cues from normalized script mentions. Render each subtitle row with a stable color palette and independently configurable word and line spacing.

**Tech Stack:** Python, Pydantic, Pillow, pytest

## Global Constraints

- Keep the mascot anchor centered.
- Use no more than two cues per non-hook beat.
- Preserve the required three-cue intro and thumbs-up outro.
- Keep captions at no more than four words and two rows.
- Do not add source-code comments.

---

### Task 1: Balanced comparison choreography

**Files:**
- Modify: `src/app/services/reference_direction_validator.py`
- Modify: `src/app/services/reference_direction_service.py`
- Test: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: `ReferenceScriptPackage` and an LLM-produced `DirectionPlan`
- Produces: `ReferenceDirectionValidator.align_with_script(plan, script) -> DirectionPlan`

- [ ] **Step 1: Write the failing regression test**

Create a script whose item is `Ciocolată topită` and whose beats say `Ciocolata topită`, then assert every two-sided body beat receives one left cue and one right cue at the corresponding word indices.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_reference_generation.py -k "balances_two_sided" -v`

Expected: the current plan contains only `point_up_left` cues.

- [ ] **Step 3: Implement deterministic balancing**

Normalize Unicode accents and punctuation, locate item phrases by token overlap, and replace two-sided body cues with ordered `point_up_left` and `point_up_right` cues. Preserve the intro and closing rules.

- [ ] **Step 4: Strengthen the direction prompt**

Add explicit correct and incorrect examples that require two cues when one beat discusses both sides.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/unit/test_reference_generation.py -v`

Expected: all direction-generation tests pass.

### Task 2: Spacious colored subtitle rows

**Files:**
- Modify: `src/app/rendering/reference_renderer.py`
- Test: `tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: `CaptionCue.words` and `CaptionCue.active_word_index`
- Produces: two-row Pillow rendering with wider gaps and alternating deep-blue/deep-purple cards

- [ ] **Step 1: Write failing layout tests**

Assert word gaps use 0.38 em, line height uses 1.38 em, and the first and second caption rows use distinct configured colors.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption" -v`

Expected: current 0.28 em gaps, 1.22 em line height, and identical dark cards fail the assertions.

- [ ] **Step 3: Implement layout constants and row palette**

Use a 0.38 em word gap, 1.38 em line height, extra vertical card padding, and colors `(39, 60, 117)` and `(95, 61, 196)`.

- [ ] **Step 4: Run focused renderer tests**

Run: `python -m pytest tests/unit/test_reference_renderer.py -v`

Expected: all renderer tests pass.

### Task 3: Pipeline verification

**Files:**
- Verify: `tests/`

**Interfaces:**
- Consumes: completed direction and rendering changes
- Produces: regression-tested video pipeline

- [ ] **Step 1: Run the complete suite**

Run: `python -m pytest tests/ -q`

Expected: all tests pass.

- [ ] **Step 2: Render and inspect representative frames**

Render frames using the affected job script and verify the body alternates left/right direction while subtitles have visibly wider spacing and colored row cards.
