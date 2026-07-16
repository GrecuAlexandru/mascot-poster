# Hook Staging, Product Normalization, and Mandatory Pair Validation Design

## Objective

Make the opening three seconds feel intentionally staged and improve product legibility throughout the video. Products, labels, mascot poses, and narration must change together on spoken-word timing. Product assets must be normalized from visible non-white content, fill the top comparison area consistently, and pass mandatory paired-image validation before rendering.

This design supersedes the earlier decision to disable production pair validation.

## Scope

The change covers three connected behaviors:

- Explicit hook reveal events compiled from narration timing.
- Larger, content-aware product normalization and matched rendering.
- Mandatory production pair validation, one-shot repair, provenance, and final quality enforcement.

Thumbnail design, caption styling, script wording, topic selection, and non-reference rendering remain unchanged.

## Hook Reveal Model

### Domain model

Add `VisualEventKind` with exactly three string values:

- `reveal_left`
- `reveal_right`
- `show_both`

Add `VisualEvent` with:

- `kind: VisualEventKind`
- `start: float`, greater than or equal to zero
- `duration_seconds: float = 0.22`, constrained from 0.18 through 0.25 seconds

`CompiledTimeline` and `CompiledVideoSpec` gain `visual_events: list[VisualEvent]`.

### Narration-driven compilation

`TimelineCompiler` compiles visual events from the hook beat and resolved absolute direction cues:

- The first hook cue focused left becomes `reveal_left`.
- The first later hook cue focused right becomes `reveal_right`.
- The first later hook cue focused both becomes `show_both`.

The director already anchors those cues to the words naming the left item, right item, and the question beginning with “Dar.” Reusing the resolved cue timestamps keeps product reveals synchronized with mascot pose changes and TTS pacing.

If the required hook cues cannot be resolved, compile deterministic fallbacks:

- `reveal_left` at 0.0 seconds
- `reveal_right` at 1.2 seconds
- `show_both` at 2.0 seconds

Fallback events are clamped into the hook beat and must remain monotonic. A short or malformed hook may compress the gaps, but the order cannot change.

The compiler produces exactly one event of each kind. Events are ordered by start time.

### Visibility semantics

Before `reveal_left`, neither product nor object label is visible. At `reveal_left`, the left product and label enter. The right side remains empty. At `reveal_right`, the right product and label enter. At `show_both`, both products and labels remain fully visible and the existing both-focused mascot pose frames the question.

Each side’s reveal progress is calculated independently from its event:

`progress = clamp((time - start) / duration, 0, 1)`

Use cubic ease-out. Opacity goes from zero to one. Entrance scale goes from 0.86 to 1.0 and multiplies the existing focus scale. The event does not move the product center or alter its matched base extent.

`show_both` is an explicit hook milestone and quality signal; it does not reanimate already visible products.

If a legacy `CompiledVideoSpec` has no visual events, the renderer preserves the existing always-visible behavior for compatibility with stored checkpoints and non-production tests.

## Product Layout and Rendering

### Template geometry

The product section should occupy approximately 35% of the 1920-pixel frame. Update `reference_v1` so the two image regions start near the current top margin and extend to approximately y=650. Labels sit directly below the image regions, followed by captions and the mascot without overlap.

The exact approved regions are:

- Left image: `[35, 70, 485, 590]`
- Right image: `[560, 70, 485, 590]`
- Left label: `[35, 650, 485, 100]`
- Right label: `[560, 650, 485, 100]`
- Caption: `[70, 790, 940, 220]`
- Mascot and CTA regions remain unchanged unless tests prove an overlap.

The paired product area therefore occupies 34.4% of frame height from y=0 through y=660.

### Visible-content detection

Introduce a shared `ProductAssetNormalizer` service so image acquisition, validation, and rendering use one definition of visible subject bounds.

For RGBA assets:

1. Composite the source over pure white for color inspection.
2. Create a non-white mask where a pixel’s maximum channel distance from white exceeds 32.
3. Combine that mask with meaningful alpha, defined as alpha at least 16.
4. Find the combined visible-content bounding box.

This keeps transparent cutouts, ordinary white-background product photos, and outlined near-white products usable. Near-white interior pixels are retained because the bounding box is used for cropping; the mask is not applied destructively to the subject.

The normalizer crops to the visible bounds plus a six-pixel source-space margin. It outputs a tightly cropped RGBA asset without adding a new square canvas. The original object pixels and alpha inside the crop are preserved.

### Source occupancy gate

Before normalization, calculate:

- `width_occupancy = visible_bbox_width / source_width`
- `height_occupancy = visible_bbox_height / source_height`
- `major_occupancy = max(width_occupancy, height_occupancy)`

Reject the candidate when `major_occupancy < 0.55`. This measures the object’s largest meaningful dimension, so naturally tall or wide products are not penalized for empty space on the other axis.

The rejection is a media-validation failure and may trigger the existing generated-image retry. The generation prompt changes its requested subject occupancy from about 72% to 85–92%, targeting 88%.

### Matched pair rendering

The renderer loads normalized content-aware images. It computes one shared base height equal to 88% of the image-region height. Each subject is scaled to that common visual height unless doing so would exceed 92% of its region width; in that case, both sides use the smaller common scale required to keep both subjects within their regions.

The resulting pair must satisfy:

- Same rendered visual height within one pixel before focus animation.
- Neither rendered subject exceeds 92% of its tile width or height.
- At least one dimension of each rendered subject occupies 85–92% of its tile at neutral focus.
- Both subjects remain centered in their own tiles.

The existing 1.28 focus zoom is reduced to 1.12 because larger base products otherwise overflow. Focus animation remains 180ms and is multiplied after entrance scale.

## Mandatory Pair Validation

### Production wiring

Create one `ReferenceImageValidator` instance in the reference-generation factory and pass it to:

- `ReferenceImageService.validator` for real candidate item validation.
- `VideoGenerationService.image_validator` for mandatory paired validation after both selected assets are normalized.

The vision provider remains a required production dependency.

### Pipeline contract

When a paired image brief exists, the pipeline must have an image validator. Missing validator configuration raises `RuntimeError("Paired image validation is required")` before rendering.

The pair is validated once. If the initial result needs repair, use the existing one-shot targeted repair behavior:

- Repair only left when `repair_side` is left.
- Repair only right when `repair_side` is right.
- Generate and split one paired image when `repair_side` is both.
- Never run more than one repair generation.

Normalize and run deterministic occupancy checks on repaired assets before final pair validation.

After the repair opportunity:

- Fatal identity, text, prohibited-content, background, realism, confidence, or occupancy failures stop the job.
- Residual scale, crop, position, lighting, or style differences may continue as warnings under the existing final policy.
- `pair_validation` must never be null for a production job with a paired brief.

### Provenance and final quality

`image_provenance.json` continues storing initial validation, final validation, repair metadata, and warnings. It additionally stores deterministic asset metrics for each side:

- Source dimensions
- Visible-content bounds
- Width, height, and major occupancy
- Normalized dimensions

`ReferenceQualityService.validate` gains the provenance path or parsed validation state needed to reject:

- Missing image provenance.
- Null final `pair_validation`.
- Missing deterministic asset metrics.
- Either `major_occupancy` below 0.55.
- Missing or incorrectly ordered hook visual events.

This prevents a job with `pair_validation: null` from passing final quality.

## Error Handling

- No visible non-white content: reject the image with `No product content detected`.
- Source major occupancy below 0.55: reject with the measured occupancy.
- No paired brief: preserve current fallback acquisition behavior and do not require semantic pair validation.
- Paired brief but missing validator: fail before render.
- Pair validator error: fail the image stage; do not silently write null validation.
- Legacy compiled specs without visual events: render both products as before, but new production compilation always includes all three events.
- Hook parsing failure: use monotonic fallback reveal times.

## Testing

### Timeline tests

- Compile left, right, and both reveal events from actual hook word timestamps.
- Verify event times equal the corresponding direction cue times.
- Verify fallback timing and ordering for missing hook cues.
- Verify production compilation always emits exactly three events.

### Renderer tests

- No products or labels before the first reveal.
- Only the left product and label after `reveal_left`.
- Both sides after `reveal_right`.
- Entrance opacity and scale progress over exactly 220ms.
- Existing mascot pose changes occur on the same timestamps.
- Neutral pair heights match within one pixel.
- Base subject occupancy is within 85–92% of the tile.
- Legacy specs without events remain always visible.

### Normalizer tests

- Crop a white-background image to non-white content rather than alpha bounds.
- Preserve near-white subject interiors.
- Correctly handle transparent cutouts.
- Reject sources below 55% major occupancy.
- Accept tall and wide sources when one dimension clears 55%.
- Emit deterministic metrics.

### Pipeline and quality tests

- Production factory shares one validator between item and pair validation.
- A paired brief without a validator fails.
- Null pair validation cannot reach a successful quality report.
- One-shot targeted repair behavior remains intact.
- Final provenance contains occupancy metrics and non-null validation.
- Hook visual-event quality rejects missing or unordered events.
- Full existing suite remains green.

## Non-Goals

This change does not:

- Add new mascot artwork or poses.
- Change the narration text or TTS voice.
- Restyle karaoke captions.
- Add camera movement beyond reveal scale/fade and existing focus zoom.
- Add repeated pair-repair loops.
- Require pair validation when no structured paired brief exists.
- Modify thumbnail composition.
