# Video Ending, Image Validation, and Mascot Calibration Design

## Objective

Improve the one-click reference video pipeline in three connected areas:

1. Every narration ends with a complete, conclusive verdict and the final spoken word is never truncated.
2. Product images depict the requested comparison items, use strong pair-consistent generation prompts, and cannot be replaced by logos or unrelated images.
3. Every mascot pose can be calibrated through one editable JSON file and previewed on a fixed 1080×1920 canvas with a shared reference dot.

## Evidence From the Reviewed Render

The reviewed job `a2aab509-0301-4026-a50d-3d5ab9716af7` exposed the following concrete failures:

- The final narration line was `Pe termen lung, lipsa fibrelor din pâinea albă.`, which sounds like a sentence fragment instead of a clear verdict.
- The transcript timeline ended at 25.678 seconds, the concatenated narration WAV ended at 25.356 seconds, and the mixed AAC ended at 25.400 seconds.
- The silent video was 25.700 seconds, but final muxing used `-shortest`, producing a 25.400-second result.
- The CTA started before narration finished because its start was calculated as narration duration minus 1.8 seconds.
- The selected left image was an Open Food Facts logo served from an `/images/logos/` URL, although its label was `Pâine albă`.
- The generated whole-wheat bread prompt only described a generic isolated object and did not specify the visual differences between white and whole-wheat bread.

## Narration Ending Contract

`ReferenceScriptPackage` will contain a dedicated closing beat. The closing beat is spoken and remains part of the exact timed transcript.

The closing beat must:

- have the stable ID `closing`;
- contain one or two complete sentences;
- end with `.`, `!`, or `?`;
- contain an explicit verdict, takeaway, or actionable conclusion;
- avoid introducing new unsupported claims;
- use `pause_after_ms` of 500 or 750;
- contain between 6 and 28 spoken words.

The final-script prompt will require the closing beat explicitly. Script validation will reject missing, fragmentary, or improperly paused closing beats and send deterministic repair notes to the script model.

Fact verification remains mandatory after any closing-beat repair.

## Compiled Timing and Outro Contract

Narration timing and total media timing will be separate values.

- `narration_end_seconds` is the maximum of the final timed word, final timed beat, and probed concatenated narration duration.
- `outro_duration_seconds` defaults to 1.8 seconds.
- `total_duration_seconds` equals `narration_end_seconds + outro_duration_seconds`.
- The CTA starts at `narration_end_seconds`, never before it.
- Captions disappear at the end of the final timed word.
- A CTA sting is anchored at `narration_end_seconds`.
- Mixed audio is padded to `total_duration_seconds`.
- The frame compositor renders through `total_duration_seconds`.
- Final muxing may retain `-shortest` only after both streams have been compiled to the same duration.

If provider timestamps exceed decoded audio duration, the audio is padded rather than shortening or clamping timed words. Quality validation rejects any final media stream shorter than `total_duration_seconds` by more than one video frame.

The existing 20–60 second target applies to spoken narration. The deterministic 1.8-second outro may extend final media duration beyond the selected narration target.

## Paired Product Image Brief

A new structured `PairedImageBrief` will be generated once per comparison before image acquisition. It contains:

- shared composition, camera angle, lighting, scale, crop, and background rules;
- a left `ProductImageBrief`;
- a right `ProductImageBrief`;
- exact subject identity for each side;
- visible distinguishing attributes;
- required inclusions;
- prohibited attributes and confusing alternatives;
- whether packaging, branding, text, slices, seeds, or props are allowed.

For the reviewed bread comparison, an appropriate brief would distinguish pale white crumb and a light crust from visibly brown whole-grain crumb and grain texture while requiring the same three-quarter camera angle and object scale.

## Real Image Candidate Validation

Real search remains the first acquisition path, but a candidate must pass all gates:

1. Download and media validation: valid image bytes, adequate dimensions, usable alpha or white background.
2. URL and metadata rejection: logo, icon, sprite, social-preview, placeholder, avatar, favicon, and branding-only paths are rejected.
3. Semantic visual validation: a vision-capable OpenRouter model receives the candidate and structured item brief and returns strict JSON.
4. Pair compatibility: accepted left and right images must use reasonably compatible subject scale, crop, and viewing angle.

The semantic result contains:

- `depicts_requested_item`;
- `distinguishing_attributes_present`;
- `contains_logo_or_prominent_text`;
- `contains_prohibited_content`;
- `background_acceptable`;
- `pair_style_acceptable`;
- `rejection_reasons`;
- `confidence`.

Candidates require positive identity, no prohibited content, acceptable background, and minimum confidence 0.8.

Every attempted candidate and rejection reason is stored in `image_provenance.json`.

## AI Image Generation and Retry

If real candidates are exhausted, OpenRouter image generation uses the structured brief rather than the item name alone.

The generated prompt includes:

- the exact subject and comparison side;
- visible attributes that distinguish it from the other item;
- shared pair composition and camera settings;
- centered full-object framing with consistent occupied area;
- transparent PNG output;
- neutral, even studio lighting;
- explicit negatives for text, logos, watermarks, packaging, unrelated objects, cropped edges, and the opposing item’s defining attributes.

Generated results pass the same semantic visual validator. Up to three generated attempts are allowed. Each retry incorporates the previous validator rejection reasons. Production fails with a stage-specific error if no generated result passes validation.

## Mascot Calibration Data

The editable file will be stored at:

`assets/mascots/default/pose_calibration.json`

Its structure is:

```json
{
  "canvas": {"width": 1080, "height": 1920},
  "reference_dot": {"x": 540, "y": 1670, "radius": 9, "color": [255, 0, 90, 255]},
  "source_pivot": {"x": 384, "y": 744},
  "base_render_height": 533,
  "poses": {
    "neutral": {"x": 540, "y": 1670, "scale": 1.0}
  }
}
```

All 24 poses from `mascot_meta.json` must be present. `x` and `y` represent the destination of the mascot’s source foot pivot. `scale` is relative to the current 533-pixel baseline render height. The fixed reference dot is rendered after the mascot so it remains visible at exactly `(540, 1670)` in every calibration image.

## Calibration Generator

The new command will be:

```bash
python scripts/generate_mascot_calibration.py
```

Optional arguments will select the mascot set, configuration file, and output directory.

Default output is `output/mascot_calibration/` and contains:

- one 1080×1920 PNG per pose, named `<pose>.png`;
- `contact-sheet.jpg` showing every pose and pose name;
- `calibration-index.json` recording canvas size, fixed dot coordinates, resolved pose pivot, scale, and output path.

Each PNG uses a pure white background, the calibrated mascot pose, the fixed magenta reference dot, and a small pose-name label outside the mascot bounds.

The script validates configuration completeness, numeric ranges, source asset presence, canvas dimensions, and output coordinates before writing images.

## Renderer Integration

`ReferenceRenderer` will load `pose_calibration.json` once.

- Pose-specific scale is applied relative to the existing baseline mascot size.
- The pose source pivot is mapped to the configured destination `x` and `y`.
- Anchor movement remains supported by adding the left/center/right anchor displacement to the calibrated center position.
- Pop animation scales around the calibrated foot pivot rather than the image center.
- Missing or invalid pose calibration is a preflight error, not a silent fallback.

The calibration reference dot is never rendered in production videos.

## Pipeline Data Flow

The updated one-click flow is:

1. Generate topic and research.
2. Generate paired image brief.
3. Search, reject, and semantically validate real image candidates in parallel.
4. Generate and validate AI fallbacks when needed.
5. Generate and fact-check the narration, including the dedicated closing beat.
6. Synthesize timed beat audio.
7. Probe decoded narration and compile narration end plus deterministic outro.
8. Generate direction cues against the final script.
9. Mix narration, timed SFX, closing silence, and CTA sting to the compiled total duration.
10. Render frames through the same total duration using calibrated mascot poses.
11. Mux and run content, stream-duration, image-provenance, and safe-zone quality gates.

## Error Handling and Checkpoints

- Image validation failures record exact candidate and rejection data.
- Generated image retries are checkpointed independently per comparison side.
- A repaired closing beat invalidates TTS, direction, compiled timeline, render, and quality checkpoints.
- A timing mismatch invalidates audio mix, render, and quality checkpoints without repeating research or image acquisition.
- Calibration configuration errors identify the exact missing pose or invalid field.
- Existing successful stages remain reusable on Retry.

## Tests

Unit and integration coverage will include:

- required closing beat, sentence completeness, pause policy, and repair notes;
- decoded-audio/timed-word mismatch and deterministic audio padding;
- CTA start after final speech and exact 1.8-second outro;
- equal compiled audio/video duration within one frame;
- rejection of `/logos/`, social-preview, text-heavy, and semantically incorrect candidates;
- detailed paired generation prompts and retry prompts containing rejection feedback;
- semantic validator acceptance thresholds and provenance history;
- all 24 calibration entries present;
- 24 generated PNGs at exactly 1080×1920;
- identical reference-dot pixels and coordinates in every PNG;
- pose-specific pivot and scale application;
- production renderer loading calibration without rendering the reference dot;
- end-to-end fake-provider generation with a complete conclusion and non-truncated outro.

## Acceptance Criteria

- The last spoken line is a complete verdict or takeaway.
- No spoken word, subtitle, CTA sting, or final frame is truncated.
- CTA begins after narration and remains visible for 1.8 seconds.
- Neither comparison image can be a logo or unrelated asset.
- AI prompts specify exact subject identity, pair style, distinguishing features, and negative constraints.
- Both product images pass semantic validation and have compatible presentation.
- The calibration command creates 24 editable-reference PNGs at 1080×1920.
- Every calibration PNG contains the same visible dot at `(540, 1670)`.
- Editing a pose’s `x`, `y`, or `scale` in JSON changes both its calibration preview and its production-render placement.
- Existing one-click generation, checkpoints, publishing, analytics, API, and n8n capabilities remain intact.
