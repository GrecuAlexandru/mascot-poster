# Pose Direction, Narration Pacing, and Cost Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every mascot pose on one calibrated foot pivot, generate expressive beat-level direction, speak at 0.8 speed, and expose a complete per-job actual-versus-estimated cost report.

**Architecture:** Add a deterministic direction validator/fallback between the direction LLM and timeline compilation. Add an async-context-local `JobCostLedger` that provider boundaries populate without shared mutable state, then persist and expose it through `RenderResult` and Streamlit.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio context variables, ElevenLabs, OpenRouter, Tavily/Serper, Pillow, FFmpeg, Streamlit, pytest.

## Global Constraints

- The mascot remains on `mascot_anchor=center`; pose swaps do not move its calibrated foot pivot.
- The one-click reference workflow uses ElevenLabs `speed=0.8`; legacy workflows retain current defaults.
- Narration remains within 20–60 seconds and the CTA remains a separate 1.8-second outro.
- Actual provider cost is preferred; estimates are explicitly labeled.
- Failed calls, retries, and cache hits remain visible in the job ledger.
- Existing API, publishing, analytics, n8n, and legacy render contracts remain compatible.
- Preserve `data/topic_history.json` and the uploaded review video as user-owned files.

---

### Task 1: Stationary Expressive Direction

**Files:**
- Create: `src/app/services/reference_direction_validator.py`
- Modify: `src/app/services/reference_direction_service.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: `ReferenceScriptPackage`, an LLM-produced `DirectionPlan`, `MascotPose`, `Focus`, and `SfxKind`.
- Produces: `ReferenceDirectionValidator.validate(plan, script) -> list[str]`, `normalize(plan) -> DirectionPlan`, and `fallback(script) -> DirectionPlan`.

- [ ] **Step 1: Write failing direction tests**

Add tests asserting that an all-neutral, left/right-anchor plan is repaired or replaced; every returned cue is center anchored; left and right beats point in their corresponding directions; no beat has more than two cues; and a valid expressive plan remains valid.

```python
def test_direction_service_replaces_all_neutral_anchor_travel():
    result = asyncio.run(ReferenceDirectionService(AllNeutralLLM()).generate(script, "ro"))
    assert all(cue.mascot_anchor == MascotAnchor.CENTER for cue in result.cues)
    assert any(cue.mascot_pose != MascotPose.NEUTRAL for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_LEFT for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_RIGHT for cue in result.cues)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py -k direction -v`

Expected: FAIL because `ReferenceDirectionValidator` and repair/fallback behavior do not exist.

- [ ] **Step 3: Implement validation and deterministic fallback**

Validation returns exact problems for invalid anchors, invalid word indexes, all-neutral plans, more than two cues per beat, consecutive no-op cues, and focus/pointing mismatches. Normalization center-anchors every cue and converts stationary pose changes to `POSE_POP`. Fallback creates one cue at word zero for each beat, alternating semantically between hook, left, right, explanation, and conclusion poses while using item-name mentions when available.

- [ ] **Step 4: Add one structured repair attempt**

Update `ReferenceDirectionService.generate` to validate the first plan, request one repaired `DirectionPlan` with the exact problems, then use deterministic fallback if repair is still invalid. Tighten the prompt to request one cue per beat, at most two, center anchors only, and explicit pose diversity.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_reference_pipeline.py -v`

```powershell
git add src/app/services/reference_direction_validator.py src/app/services/reference_direction_service.py tests/unit/test_reference_generation.py
git commit -m "generate stationary expressive mascot direction"
```

---

### Task 2: Slower Beat Narration and Calibration Acceptance

**Files:**
- Modify: `src/app/services/video_generation_service.py`
- Modify: `src/app/services/reference_script_service.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_mascot_calibration.py`

**Interfaces:**
- Consumes: `BeatTTSService.synthesize(..., settings: TTSSettings)` and `pose_calibration.json`.
- Produces: reference-workflow TTS calls using `TTSSettings(speed=0.8)` and pivot-equality acceptance coverage.

- [ ] **Step 1: Write failing pacing and pivot tests**

```python
def test_reference_generation_synthesizes_at_eighty_percent_speed():
    asyncio.run(service.generate(GenerationRequest()))
    assert fake_tts.settings.speed == pytest.approx(0.8)

def test_neutral_and_pointing_previews_share_target_pivot(settings):
    calibration = MascotCalibrationService(settings.mascots_dir).load()
    pivots = [calibration.poses[name] for name in ("neutral", "point_left", "point_right")]
    assert {(pose.x, pose.y) for pose in pivots} == {(540.0, 1670.0)}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_mascot_calibration.py -k "speed or pointing" -v`

Expected: pacing test FAIL because `VideoGenerationService` does not pass settings.

- [ ] **Step 3: Pass explicit reference TTS settings**

Call `beat_tts.synthesize(..., settings=TTSSettings(speed=0.8))`. Update the script prompt to prefer 300–500 ms body pauses, reserve 150 ms for connected phrases, and use 750 ms for the closing.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_mascot_calibration.py tests/unit/test_tts.py -v`

```powershell
git add src/app/services/video_generation_service.py src/app/services/reference_script_service.py tests/unit/test_reference_pipeline.py tests/unit/test_mascot_calibration.py
git commit -m "slow reference narration and preserve pose pivot"
```

---

### Task 3: Concurrency-Safe Job Cost Ledger

**Files:**
- Modify: `src/app/domain/models.py`
- Create: `src/app/services/job_cost_ledger.py`
- Modify: `src/app/services/cost_tracker.py`
- Create: `tests/unit/test_job_cost_ledger.py`

**Interfaces:**
- Produces: `CostEvent`, `CostReport`, `JobCostLedger.record(...)`, `JobCostLedger.save(path)`, `cost_scope(ledger, stage)`, and `record_cost_event(...)`.

- [ ] **Step 1: Write failing ledger tests**

Test actual and estimated totals, grouping by provider/stage/operation/model/amount kind, failed calls, cache hits, deterministic event deduplication, JSON persistence, and isolation across two concurrent asyncio tasks.

```python
async def test_cost_scopes_are_isolated_between_jobs(tmp_path):
    async def record(job_id):
        ledger = JobCostLedger(job_id)
        with cost_scope(ledger, "tts"):
            record_cost_event(provider="elevenlabs", operation="synthesize", amount_usd=0.01)
        return ledger
    first, second = await asyncio.gather(record("a"), record("b"))
    assert first.events[0].job_id == "a"
    assert second.events[0].job_id == "b"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_job_cost_ledger.py -v`

Expected: collection fails because the ledger module does not exist.

- [ ] **Step 3: Implement models, context scope, grouping, and persistence**

Use `ContextVar` for the active ledger and stage. Generate stable event IDs from job, stage, provider, model, operation, attempt, and an optional request key. Preserve six-decimal monetary precision. `record_cost_event` is a no-op outside a scope.

- [ ] **Step 4: Keep legacy tracker compatible**

Retain all current `CostTracker` methods and output keys while allowing it to construct equivalent estimated events internally.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/unit/test_job_cost_ledger.py tests/unit/test_platform.py -v`

```powershell
git add src/app/domain/models.py src/app/services/job_cost_ledger.py src/app/services/cost_tracker.py tests/unit/test_job_cost_ledger.py
git commit -m "add per-job cost ledger"
```

---

### Task 4: Provider and Service Cost Instrumentation

**Files:**
- Modify: `src/app/providers/llm/openai_provider.py`
- Modify: `src/app/providers/images/openrouter_provider.py`
- Modify: `src/app/providers/search/tavily_provider.py`
- Modify: `src/app/services/beat_tts_service.py`
- Modify: `src/app/services/reference_image_service.py`
- Modify: `tests/unit/test_reference_assets.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_job_cost_ledger.py`

**Interfaces:**
- Consumes: `record_cost_event` in the current cost scope.
- Produces: one event per OpenRouter completion/image attempt, search request, image download attempt, ElevenLabs beat, retry, failure, and cache hit.

- [ ] **Step 1: Write failing instrumentation tests**

Mock raw provider responses containing `usage.cost` and responses without it. Assert `actual` for reported cost, `estimated` for fallback prices, an estimated ElevenLabs event per beat, zero-cost cached image events, and failed attempt visibility.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_job_cost_ledger.py tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py -k cost -v`

Expected: FAIL because providers do not record ledger events.

- [ ] **Step 3: Instrument OpenRouter completions and images**

Read `usage.cost` before falling back to `estimate_cost`. Record input/output tokens, model, amount kind, attempt, success, and cache status. Record a failed zero-cost event before raising non-billable HTTP errors.

- [ ] **Step 4: Instrument search, downloads, and TTS beats**

Record each search response's estimate, each download attempt as zero-cost external acquisition, and every returned `TTSResult` using characters and `estimated_cost_usd`. Preserve original exceptions when recording fails.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/unit/test_job_cost_ledger.py tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py tests/unit/test_tts.py -v`

```powershell
git add src/app/providers/llm/openai_provider.py src/app/providers/images/openrouter_provider.py src/app/providers/search/tavily_provider.py src/app/services/beat_tts_service.py src/app/services/reference_image_service.py tests/unit/test_job_cost_ledger.py tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py
git commit -m "record external provider costs"
```

---

### Task 5: Pipeline Persistence and Streamlit Cost Diagnostics

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/video_generation_service.py`
- Modify: `streamlit_app.py`
- Modify: `README.md`
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `tests/unit/test_reference_assets.py`

**Interfaces:**
- Produces: `RenderResult.cost_report_path`, persisted `cost_report.json`, checkpoint-safe append/deduplication, Streamlit totals/table/download.

- [ ] **Step 1: Write failing pipeline/UI tests**

Assert that generation creates `cost_report.json`, exposes it on `RenderResult`, includes local zero-cost render/SFX operations, reuses checkpoint costs without duplication, and lists `Cost report` among Streamlit diagnostic artifacts.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_reference_assets.py -k cost -v`

Expected: FAIL because `cost_report_path` and pipeline persistence do not exist.

- [ ] **Step 3: Wrap stages and persist the ledger**

Create/load the job ledger at generation start. Enter a named `cost_scope` around each stage, append local zero-cost compilation/render/SFX events, save after every stage and on failure, and set `RenderResult.cost_report_path` before returning.

- [ ] **Step 4: Render cost diagnostics in Streamlit**

Show projected total, actual total, estimated-only total, billable-call count, a table with stage/provider/model/operation/units/kind/USD/status, and a JSON download button.

- [ ] **Step 5: Document commands and verify acceptance**

Document:

```powershell
python scripts/generate_mascot_calibration.py
python scripts/render_reference_acceptance.py
python -m pytest tests/ -v
```

Run the full suite, asset validation, calibration generation, and offline acceptance render. Inspect that neutral/left/right share `(540, 1670)`, all compiled anchors are center, the voice fake receives speed `0.8`, and the cost report totals its events exactly.

- [ ] **Step 6: Commit and push**

```powershell
git add README.md streamlit_app.py src tests docs/superpowers/plans/2026-07-11-pose-pacing-cost-ledger-implementation.md
git commit -m "complete pose pacing and cost reporting"
git push origin main
```

## Plan Self-Review

- Spec coverage: stationary direction, expressive poses, deterministic fallback, slower speech, pause guidance, calibration acceptance, actual/estimated costs, failures, retries, cache hits, concurrency, checkpoints, JSON persistence, Streamlit diagnostics, and compatibility each map to a task.
- Placeholder scan: no deferred implementation markers or unspecified code steps remain.
- Type consistency: `CostEvent`, `CostReport`, `JobCostLedger`, `cost_scope`, `record_cost_event`, `ReferenceDirectionValidator`, and `RenderResult.cost_report_path` use the same names across producer and consumer tasks.
- Scope: direction, pacing, and cost reporting share the one-click pipeline lifecycle and form one testable delivery.
