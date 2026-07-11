# Video Quality and Mascot Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee conclusive, non-truncated reference videos with semantically correct paired product images and an editable 24-pose mascot calibration workflow.

**Architecture:** Add explicit closing and compiled-media timing contracts, a structured paired-image brief with OpenRouter vision validation, and a JSON-driven mascot calibration service shared by the preview generator and production renderer. Keep all provider calls behind interfaces and preserve the existing one-click checkpoint pipeline.

**Tech Stack:** Python 3.11+, Pydantic v2, Pillow, FFmpeg/FFprobe, httpx, OpenRouter structured outputs, pytest, Streamlit.

## Global Constraints

- Reference canvases remain exactly 1080×1920 at 30 fps with a pure white background.
- Narration target remains 20–60 seconds; final media adds a deterministic 1.8-second outro.
- CTA starts after the last spoken word and remains visible for exactly 1.8 seconds.
- Calibration reference dot remains fixed at `(540, 1670)` in every preview and is never rendered in production.
- All 24 poses declared in `mascot_meta.json` must have editable `x`, `y`, and `scale` values.
- External providers remain behind interfaces; secrets remain environment variables.
- FFmpeg commands remain argument lists and never use shell interpolation.
- Existing publishing, analytics, API, n8n, and legacy render contracts remain compatible.

---

### Task 1: Repository Hygiene and Safe Initial Publication

**Files:**
- Create: `.gitignore`
- Modify: none
- Test: local Git status and secret scan

**Interfaces:**
- Consumes: current local workspace and user-specified GitHub remote.
- Produces: a source-only `main` branch without `.env`, runtime output, caches, bytecode, or generated upload videos.

- [ ] **Step 1: Add explicit ignore rules**

```gitignore
.env
.venv/
venv/
__pycache__/
*.py[cod]
.pytest_cache/
cache/
output/
*.egg-info/
f974782a17d2265a1c292c7b05ef0d70.mp4
```

- [ ] **Step 2: Initialize Git and inspect staged scope**

Run:

```powershell
git init
git branch -M main
git add -A
git status --short
```

Expected: source, tests, mascot assets, `reference_video.mp4`, the design, and this plan are staged; ignored runtime and secret files are absent.

- [ ] **Step 3: Scan staged paths for secrets and generated runtime files**

Run:

```powershell
git diff --cached --name-only
git grep --cached -n -I -E "(sk-or-|sk-[A-Za-z0-9]{20,}|ELEVENLABS_API_KEY=.+|OPENROUTER_API_KEY=.+)"
```

Expected: no populated secret values and no `output/`, `cache/`, `.env`, `__pycache__`, or uploaded generated MP4.

- [ ] **Step 4: Commit and push the approved initial scope**

Run:

```powershell
git commit -m "first commit"
git remote add origin https://github.com/GrecuAlexandru/mascot-poster.git
git push -u origin main
```

Expected: `main` tracks `origin/main`.

---

### Task 2: Mascot Calibration Contract and Generator

**Files:**
- Create: `src/app/services/mascot_calibration_service.py`
- Create: `assets/mascots/default/pose_calibration.json`
- Create: `scripts/generate_mascot_calibration.py`
- Create: `tests/unit/test_mascot_calibration.py`
- Modify: `src/app/rendering/reference_renderer.py`
- Modify: `scripts/validate_assets.py`

**Interfaces:**
- Consumes: `mascot_meta.json`, transparent 768×768 pose PNGs, and `pose_calibration.json`.
- Produces: `PoseCalibration`, `MascotCalibration`, `MascotCalibrationService.load()`, `render_pose()`, `render_all()`, plus renderer pivot placement.

- [ ] **Step 1: Write failing calibration model and output tests**

```python
def test_calibration_contains_every_pose_and_fixed_dot(settings):
    service = MascotCalibrationService(settings.mascots_dir)
    calibration = service.load()
    assert set(calibration.poses) == set(MascotService(settings.mascots_dir).available_poses)
    assert (calibration.reference_dot.x, calibration.reference_dot.y) == (540, 1670)


def test_render_all_creates_24_full_size_images_with_identical_dot(tmp_path, settings):
    outputs = MascotCalibrationService(settings.mascots_dir).render_all(tmp_path)
    assert len(outputs) == 24
    for path in outputs.values():
        image = Image.open(path).convert("RGBA")
        assert image.size == (1080, 1920)
        assert image.getpixel((540, 1670)) == (255, 0, 90, 255)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_mascot_calibration.py -v`

Expected: collection fails because `MascotCalibrationService` does not exist.

- [ ] **Step 3: Implement strict calibration models and pivot rendering**

```python
class PoseCalibration(BaseModel):
    x: float
    y: float
    scale: float = Field(gt=0.1, le=3.0)


class MascotCalibration(BaseModel):
    canvas: CanvasSpec
    reference_dot: ReferenceDot
    source_pivot: PivotSpec
    base_render_height: int = Field(gt=0)
    poses: dict[str, PoseCalibration]


class MascotCalibrationService:
    def load(self) -> MascotCalibration:
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        calibration = MascotCalibration.model_validate(payload)
        self.validate_pose_set(calibration)
        return calibration

    def render_pose(self, pose: str, show_reference_dot: bool) -> Image.Image:
        calibration = self.load()
        canvas = Image.new("RGBA", (calibration.canvas.width, calibration.canvas.height), "white")
        self.paste_calibrated_pose(canvas, pose, calibration.poses[pose])
        if show_reference_dot:
            self.draw_reference_dot(canvas, calibration.reference_dot)
        return canvas

    def render_all(self, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for pose in self.load().poses:
            path = output_dir / f"{pose}.png"
            self.render_pose(pose, show_reference_dot=True).save(path)
            outputs[pose] = path
        return outputs
```

Placement formula:

```python
height = round(calibration.base_render_height * pose.scale)
width = round(source.width * height / source.height)
pivot_x = calibration.source_pivot.x * width / source.width
pivot_y = calibration.source_pivot.y * height / source.height
paste_x = round(pose.x - pivot_x)
paste_y = round(pose.y - pivot_y)
```

- [ ] **Step 4: Add all 24 default pose entries**

Every entry starts at `{"x": 540, "y": 1670, "scale": 1.0}`. The fixed dot is `{"x": 540, "y": 1670, "radius": 9, "color": [255, 0, 90, 255]}`; source pivot is `{"x": 384, "y": 744}`; base render height is `533`.

- [ ] **Step 5: Add the CLI and contact sheet/index outputs**

```python
parser.add_argument("--mascot-dir", type=Path, default=PROJECT_ROOT / "assets" / "mascots" / "default")
parser.add_argument("--config", type=Path)
parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "mascot_calibration")
```

The CLI calls `render_all`, creates `contact-sheet.jpg`, and writes `calibration-index.json` with resolved pivots and paths.

- [ ] **Step 6: Integrate calibration into `ReferenceRenderer`**

Load calibration once in `__init__`. Place each production pose with its calibrated source pivot. Apply anchor deltas `LEFT=-240`, `CENTER=0`, `RIGHT=240` to calibrated `x`. Apply pop scaling around the calibrated foot pivot. Never draw the reference dot in production.

- [ ] **Step 7: Run tests, generator, and asset validation**

Run:

```powershell
python -m pytest tests/unit/test_mascot_calibration.py tests/unit/test_reference_renderer.py -v
python scripts/generate_mascot_calibration.py
python scripts/validate_assets.py
```

Expected: 24 PNGs, one contact sheet, one index JSON, all tests and validation pass.

- [ ] **Step 8: Commit**

```powershell
git add assets/mascots/default/pose_calibration.json scripts/generate_mascot_calibration.py scripts/validate_assets.py src/app/services/mascot_calibration_service.py src/app/rendering/reference_renderer.py tests/unit/test_mascot_calibration.py tests/unit/test_reference_renderer.py
git commit -m "add mascot pose calibration workflow"
```

---

### Task 3: Conclusive Closing Beat Contract

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/reference_script_service.py`
- Modify: `src/app/services/beat_tts_service.py`
- Modify: `src/app/services/reference_direction_service.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: factual research, language, target duration, and narration beats.
- Produces: required `ReferenceScriptPackage.closing: NarrationBeat` and `all_beats`.

- [ ] **Step 1: Write failing closing-contract tests**

```python
def test_reference_script_requires_conclusive_closing():
    with pytest.raises(ValueError, match="closing"):
        ReferenceScriptPackage(
            title="Coffee vs Tea",
            left_item="Coffee",
            right_item="Tea",
            hook="Which is better?",
            beats=[NarrationBeat(id="b1", text="Coffee acts quickly.")],
            closing=NarrationBeat(id="b8", text="A fragment", pause_after_ms=0),
            caption="Coffee or tea?",
        )


def test_all_beats_appends_closing_after_body_beats():
    script = make_reference_script(closing=NarrationBeat(
        id="closing",
        text="Așadar, pâinea integrală este alegerea mai echilibrată pentru majoritatea oamenilor.",
        pause_after_ms=500,
    ))
    assert [beat.id for beat in script.all_beats][-1] == "closing"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -v`

Expected: FAIL because `closing` and `all_beats` do not exist.

- [ ] **Step 3: Implement the closing field and validator**

```python
closing: NarrationBeat

@model_validator(mode="after")
def validate_closing(self) -> "ReferenceScriptPackage":
    words = self.closing.text.split()
    if self.closing.id != "closing":
        raise ValueError("closing beat id must be 'closing'")
    if self.closing.pause_after_ms not in (500, 750):
        raise ValueError("closing pause must be 500 or 750 ms")
    if not 6 <= len(words) <= 28:
        raise ValueError("closing must contain 6-28 words")
    if not self.closing.text.endswith((".", "!", "?")):
        raise ValueError("closing must be a complete sentence")
    return self

@property
def all_beats(self) -> list[NarrationBeat]:
    return [*self.beats, self.closing]
```

- [ ] **Step 4: Update prompts and consumers**

Require an explicit verdict/takeaway with no new unsupported claim. Iterate `script.all_beats` in TTS and include `closing` in the direction prompt. Update test fixtures and fake providers with a valid closing beat.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py -v`

```powershell
git add src/app/domain/models.py src/app/services/reference_script_service.py src/app/services/beat_tts_service.py src/app/services/reference_direction_service.py tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py
git commit -m "require conclusive narration endings"
```

---

### Task 4: Shared Audio/Video End Time and Post-Speech CTA

**Files:**
- Modify: `src/app/domain/models.py`
- Modify: `src/app/services/beat_tts_service.py`
- Modify: `src/app/services/audio_service.py`
- Modify: `src/app/services/timeline_compiler.py`
- Modify: `src/app/rendering/reference_renderer.py`
- Modify: `src/app/services/reference_render_service.py`
- Modify: `src/app/services/reference_quality_service.py`
- Modify: `src/app/services/video_generation_service.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: timed words, probed narration duration, direction SFX, and closing pause.
- Produces: `CompiledVideoSpec.narration_end_seconds`, `outro_duration_seconds`, and `total_duration_seconds`.

- [ ] **Step 1: Write failing timing tests**

```python
def test_compiled_spec_adds_outro_after_last_speech(media_paths):
    spec = make_compiled_spec(transcript_duration=25.678, narration_end_seconds=25.678)
    assert spec.total_duration_seconds == pytest.approx(27.478)
    assert spec.cta_start_seconds == pytest.approx(25.678)


def test_renderer_starts_cta_only_after_narration(spec, renderer):
    assert not renderer.cta_visible_at(spec, spec.narration_end_seconds - 0.001)
    assert renderer.cta_visible_at(spec, spec.narration_end_seconds)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_renderer.py -v`

Expected: FAIL because compiled timing fields and `cta_visible_at` do not exist.

- [ ] **Step 3: Add compiled timing fields**

```python
narration_end_seconds: float = Field(gt=0)
outro_duration_seconds: float = Field(default=1.8, ge=1.8, le=1.8)

@property
def cta_start_seconds(self) -> float:
    return self.narration_end_seconds

@property
def total_duration_seconds(self) -> float:
    return self.narration_end_seconds + self.outro_duration_seconds
```

- [ ] **Step 4: Probe narration and compile a safe narration end**

After beat concatenation, probe the decoded WAV. Set transcript duration to the maximum of decoded duration, final word end, and final beat pause end. Preserve word timings without clamping.

- [ ] **Step 5: Pad mixed audio and add CTA sting**

Extend `mix_timed_sfx` with `total_duration_seconds`. Apply `apad,atrim=duration=<total>` to narration and each delayed SFX. Add `SoundEffectCue(start=narration_end_seconds, kind=CTA_STING)` after debouncing body cues.

- [ ] **Step 6: Render the exact compiled duration**

Use `ceil(spec.total_duration_seconds * fps)` frames. CTA visibility is `narration_end_seconds <= t < total_duration_seconds`. `RenderResult.duration_seconds` is total media duration.

- [ ] **Step 7: Add final stream-duration quality gates**

Validate spoken narration against 20–60 seconds, then validate final audio/video streams against `total_duration_seconds` with tolerance `1 / fps`.

- [ ] **Step 8: Run focused and media tests, then commit**

Run:

```powershell
python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_renderer.py tests/unit/test_tts.py -v
```

```powershell
git add src/app/domain/models.py src/app/services/beat_tts_service.py src/app/services/audio_service.py src/app/services/timeline_compiler.py src/app/rendering/reference_renderer.py src/app/services/reference_render_service.py src/app/services/reference_quality_service.py src/app/services/video_generation_service.py tests/unit/test_reference_pipeline.py tests/unit/test_reference_renderer.py tests/unit/test_tts.py
git commit -m "prevent truncated narration and outro"
```

---

### Task 5: Structured Paired Image Brief and Strong Generation Prompts

**Files:**
- Modify: `src/app/domain/models.py`
- Create: `src/app/services/reference_image_brief_service.py`
- Modify: `src/app/services/reference_image_service.py`
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `src/app/services/video_generation_service.py`
- Modify: `tests/unit/test_reference_assets.py`
- Modify: `tests/unit/test_reference_generation.py`

**Interfaces:**
- Consumes: topic and research package.
- Produces: `ProductImageBrief`, `PairedImageBrief`, `ReferenceImageBriefService.generate()`, and deterministic generation prompts.

- [ ] **Step 1: Write failing brief and prompt tests**

```python
def test_generated_prompt_contains_identity_pair_style_and_negatives():
    prompt = ReferenceImageService.build_generation_prompt(brief.left, brief.shared_style, [])
    assert "white bread loaf" in prompt
    assert "pale white crumb" in prompt
    assert "same three-quarter camera angle" in prompt
    assert "no logo" in prompt
    assert "not whole-wheat bread" in prompt


def test_logo_metadata_candidate_is_rejected():
    candidate = ImageCandidate(url="https://static.example/images/logos/social-preview.png")
    assert ReferenceImageService.metadata_rejection(candidate) == "logo or social-preview asset"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_assets.py -v`

Expected: FAIL because structured briefs and prompt builder do not exist.

- [ ] **Step 3: Add strict brief models**

```python
class ProductImageBrief(BaseModel):
    item: str
    exact_subject: str
    distinguishing_attributes: list[str] = Field(min_length=1)
    required_elements: list[str] = Field(default_factory=list)
    prohibited_elements: list[str] = Field(default_factory=list)
    confusing_alternatives: list[str] = Field(default_factory=list)
    allow_packaging: bool = False
    allow_text: bool = False


class PairedImageBrief(BaseModel):
    shared_style: str
    left: ProductImageBrief
    right: ProductImageBrief
```

- [ ] **Step 4: Implement structured brief generation**

Use the direction/research Flash model with strict schema. Require shared angle, crop, lighting, occupied area, transparent background, and side-specific distinguishing attributes supported by the item names and research.

- [ ] **Step 5: Implement deterministic metadata rejection and prompt construction**

Reject URL/title/description tokens `logo`, `logos`, `icon`, `sprite`, `favicon`, `avatar`, `social-preview`, `placeholder`, and `brandmark`. The prompt concatenates exact identity, attributes, required elements, shared style, transparency, framing, and explicit negatives.

- [ ] **Step 6: Place brief generation before paired acquisition in the pipeline**

Research completes first. Then generate one paired brief and acquire both sides. Store `paired_image_brief.json` and include its path in provenance/checkpoints.

- [ ] **Step 7: Run tests and commit**

```powershell
python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_generation.py -v
git add src/app/domain/models.py src/app/services/reference_image_brief_service.py src/app/services/reference_image_service.py src/app/services/reference_generation_factory.py src/app/services/video_generation_service.py tests/unit/test_reference_assets.py tests/unit/test_reference_generation.py
git commit -m "add structured paired image briefs"
```

---

### Task 6: OpenRouter Semantic Image Validation and Retry Provenance

**Files:**
- Modify: `src/app/providers/llm/base.py`
- Modify: `src/app/providers/llm/openai_provider.py`
- Create: `src/app/services/reference_image_validator.py`
- Modify: `src/app/services/reference_image_service.py`
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `src/app/config.py`
- Modify: `.env.example`
- Modify: `tests/unit/test_reference_assets.py`
- Modify: `tests/unit/test_reference_pipeline.py`

**Interfaces:**
- Consumes: local candidate PNGs and structured image briefs.
- Produces: `complete_structured_with_images`, `ImageValidationResult`, `ReferenceImageValidator.validate_item()`, `validate_pair()`, and full attempt provenance.

- [ ] **Step 1: Write failing multimodal and semantic validation tests**

```python
def test_multimodal_request_contains_data_url(provider, png_path):
    body = provider._build_multimodal_request("system", "validate", [png_path], response_format)
    content = body["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_generated_retry_uses_validator_feedback(fake_validator, image_service):
    fake_validator.results = [reject("looks like whole-wheat bread"), accept()]
    provenance = asyncio.run(image_service.acquire(
        item="White bread",
        output_path=Path("selected.png"),
        brief=white_bread_brief(),
    ))
    assert provenance.attempts[0].rejection_reasons == ["looks like whole-wheat bread"]
    assert "looks like whole-wheat bread" in image_service.generated_prompts[1]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py -v`

Expected: FAIL because multimodal structured completion and semantic validator do not exist.

- [ ] **Step 3: Extend the LLM provider with image inputs**

```python
async def complete_structured_with_images(
    self,
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path],
    response_model: type[BaseModel],
    schema_name: str,
) -> BaseModel:
    response_format = self._strict_response_format(response_model, schema_name)
    body = self._build_multimodal_request(
        system_prompt,
        user_prompt,
        image_paths,
        response_format,
    )
    payload = await self._post_completion(body)
    content = payload["choices"][0]["message"]["content"]
    return response_model.model_validate_json(content)
```

Encode local images as MIME-correct data URLs and retain strict JSON Schema routing/fallback behavior.

- [ ] **Step 4: Implement semantic result and validator**

```python
class ImageValidationResult(BaseModel):
    depicts_requested_item: bool
    distinguishing_attributes_present: bool
    contains_logo_or_prominent_text: bool
    contains_prohibited_content: bool
    background_acceptable: bool
    pair_style_acceptable: bool = True
    rejection_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @property
    def accepted(self) -> bool:
        return (
            self.depicts_requested_item
            and self.distinguishing_attributes_present
            and not self.contains_logo_or_prominent_text
            and not self.contains_prohibited_content
            and self.background_acceptable
            and self.pair_style_acceptable
            and self.confidence >= 0.8
        )
```

- [ ] **Step 5: Validate all real and generated attempts**

Real candidates pass metadata, media, and semantic gates. Generated fallback gets three attempts, each incorporating prior rejection reasons. If final pair validation fails, regenerate the rejected/lower-confidence side and validate again.

- [ ] **Step 6: Persist full provenance**

Add `ImageAttempt` entries containing candidate URL, source URL, prompt, semantic result, rejection reasons, and selected flag. Never swallow exceptions; record a normalized failure reason.

- [ ] **Step 7: Configure an environment-overridable vision model**

Add `OPENROUTER_VISION_MODEL`, defaulting to the configured Flash model when it supports image input and otherwise to an explicit vision-capable OpenRouter model.

- [ ] **Step 8: Run tests and commit**

```powershell
python -m pytest tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py -v
git add src/app/providers/llm/base.py src/app/providers/llm/openai_provider.py src/app/services/reference_image_validator.py src/app/services/reference_image_service.py src/app/services/reference_generation_factory.py src/app/config.py .env.example tests/unit/test_reference_assets.py tests/unit/test_reference_pipeline.py
git commit -m "validate product images semantically"
```

---

### Task 7: End-to-End Integration, Retry Invalidation, and Acceptance Render

**Files:**
- Modify: `src/app/services/video_generation_service.py`
- Modify: `src/app/services/reference_quality_service.py`
- Modify: `streamlit_app.py`
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `tests/unit/test_reference_renderer.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all contracts from Tasks 2–6.
- Produces: a one-click generation result with closing, validated paired images, calibrated poses, and a complete outro.

- [ ] **Step 1: Write failing end-to-end fake-provider test**

The test supplies one logo candidate, one semantically wrong generated image, a corrected second generation, a valid closing beat, and provider timestamps longer than decoded narration. Assert the selected image attempt, closing transcript, CTA start, equal compiled durations, 24-pose calibration use, and successful quality result.

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py -v`

Expected: FAIL until all new pipeline dependencies and checkpoint payloads are connected.

- [ ] **Step 3: Wire stages and checkpoint invalidation**

Add progress labels for `image_brief` and `image_validation`. Persist brief, attempt provenance, compiled end time, and calibration version. Changes to closing invalidate script-downstream stages; image validation failures invalidate image-downstream stages only.

- [ ] **Step 4: Update final quality report and Streamlit diagnostics**

Expose paired image brief and attempt provenance downloads. Quality JSON includes narration end, CTA start, total duration, stream durations, selected image validation confidence, and calibration config path.

- [ ] **Step 5: Update README commands**

Document:

```bash
python scripts/generate_mascot_calibration.py
python scripts/validate_assets.py
streamlit run streamlit_app.py
python -m pytest tests/ -v
```

- [ ] **Step 6: Run full verification**

```powershell
python -m py_compile streamlit_app.py src/app/domain/models.py src/app/services/*.py src/app/providers/llm/*.py scripts/generate_mascot_calibration.py
python -m pytest tests/ -v
python scripts/validate_assets.py
python scripts/generate_mascot_calibration.py
```

Expected: all tests pass, all assets validate, 24 calibration PNGs exist, and no quality errors remain.

- [ ] **Step 7: Render and inspect an offline acceptance fixture**

Render a deterministic 1080×1920/30fps fixture. Probe both streams, inspect the contact sheet, inspect the final spoken-word frame, and inspect the first/last CTA frames. Expected final stream duration differs from compiled total by no more than `1/30` second.

- [ ] **Step 8: Commit and push implementation**

```powershell
git add README.md streamlit_app.py src tests scripts assets/mascots/default/pose_calibration.json .env.example
git commit -m "complete reference video quality workflow"
git push origin main
```

---

## Plan Self-Review

- Spec coverage: narration conclusion, decoded timing mismatch, post-speech CTA, semantic image validation, detailed paired prompts, retry provenance, calibration JSON, 24 previews, fixed dot, renderer integration, checkpoints, diagnostics, and acceptance validation each map to a task.
- Placeholder scan: no deferred implementation markers or incomplete code examples are present.
- Type consistency: `PairedImageBrief`, `ProductImageBrief`, `ImageValidationResult`, `MascotCalibrationService`, `ReferenceScriptPackage.closing`, and compiled timing field names remain consistent across producer and consumer tasks.
- Execution choice: the user explicitly requested immediate implementation in this workspace, so use inline execution with `superpowers:executing-plans`.
