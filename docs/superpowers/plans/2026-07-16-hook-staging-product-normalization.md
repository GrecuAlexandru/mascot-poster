# Hook Staging and Product Normalization Implementation Plan

> **For Codex:** Execute this plan task by task, using tests before implementation and verifying the complete suite before completion.

**Goal:** Stage the first three seconds around narration-driven product reveals, enlarge the comparison products through visible-subject cropping, and make paired-image validation a required production gate.

**Architecture:** The timeline compiler emits explicit visual events from resolved hook direction cues. The reference renderer consumes those events while retaining legacy always-visible behavior for old specs. A shared product normalizer owns subject detection, cropping, occupancy metrics, and rejection; the image service records those metrics in provenance, while the pipeline and quality service enforce pair validation and artifact completeness.

**Tech Stack:** Python 3.11+, Pydantic, Pillow, pytest, FFmpeg-backed renderer.

---

### Task 1: Add visual-event domain models and narration-driven compilation

**Files:**
- Modify: `src/app/domain/enums.py`
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/timeline_compiler.py`
- Modify: `src/app/services/video_generation_service.py`
- Test: `tests/unit/test_timeline_compiler.py`
- Test: `tests/unit/test_reference_generation.py`

1. Add failing tests for left, right, and both hook cues producing exactly one ordered event at their resolved word times.
2. Add failing tests for deterministic `0.0`, `1.2`, and `2.0` fallback events clamped to the hook beat.
3. Add `VisualEventKind`, `VisualEvent`, and `visual_events` fields on compiled timeline/video models.
4. Compile hook visual events from resolved absolute direction cues and pass them into `CompiledVideoSpec`.
5. Run the focused timeline and compilation tests.

### Task 2: Stage product and label entrances and enlarge the product layout

**Files:**
- Modify: `templates/comparison_v1.json`
- Modify: `src/app/rendering/reference_renderer.py`
- Test: `tests/unit/test_reference_renderer.py`

1. Add failing frame tests for left-only, then both-visible states, label synchronization, and legacy always-visible specs.
2. Add failing entrance interpolation tests for 180–250 ms cubic ease-out scale/fade motion.
3. Add failing layout tests for matched product height, 85–92% neutral tile fill, and 1.12 focus zoom.
4. Update template regions so products occupy the upper 32–38% of the frame and captions begin below them.
5. Implement event visibility, opacity, entrance scaling, synchronized labels, and a `show_both` milestone without re-animation.
6. Implement common-height pair fitting with a 92% width cap and 88% target fill.
7. Run renderer tests.

### Task 3: Normalize around visible subject pixels and record metrics

**Files:**
- Create: `src/app/services/product_asset_normalizer.py`
- Modify: `src/app/services/reference_image_service.py`
- Test: `tests/unit/test_product_asset_normalizer.py`
- Test: `tests/unit/test_reference_assets.py`

1. Add failing tests for opaque white-background detection, transparent white subjects, six-pixel crop padding, occupancy metrics, and rejection below 55% major-axis occupancy.
2. Implement a typed normalizer that composites for color inspection, uses alpha for cutouts, uses non-white distance for opaque sources, crops without square padding, and returns provenance-safe metrics.
3. Integrate normalization into sourced, generated, and repaired product paths.
4. Change generated-image prompting from 72% fill to an 85–92% range targeting 88%.
5. Add metrics to every `ImageProvenance` record and update affected asset tests.
6. Run normalizer and image-service tests.

### Task 4: Require pair validation and enforce final quality evidence

**Files:**
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `src/app/services/video_generation_service.py`
- Modify: `src/app/services/reference_quality_service.py`
- Test: `tests/unit/test_reference_pipeline.py`
- Test: `tests/unit/test_reference_generation.py`
- Test: `tests/unit/test_reference_quality.py`

1. Add failing tests that a structured paired brief cannot proceed without an image validator.
2. Add failing tests that the factory shares one validator between item acquisition and pair validation.
3. Add failing tests for one-shot repair followed by normalization and final pair validation.
4. Add failing quality tests for absent provenance, null required pair validation, missing metrics, occupancy below 55%, and incorrect visual-event contracts.
5. Wire the shared validator through the factory and raise a clear runtime error when paired validation is unavailable.
6. Mark provenance with whether pair validation was required and ensure final validation is serialized.
7. Extend final quality validation to inspect provenance metrics and the compiled visual-event set.
8. Run pipeline and quality tests.

### Task 5: Complete verification

**Files:**
- Verify all modified source, template, and test files.

1. Run focused unit tests for timeline, renderer, assets, generation, pipeline, and quality.
2. Run `python -m pytest tests/ -v`.
3. Inspect `git diff --check` and the final working-tree diff without modifying unrelated user changes.
4. Report implemented behavior, verification evidence, and any remaining caveats.
