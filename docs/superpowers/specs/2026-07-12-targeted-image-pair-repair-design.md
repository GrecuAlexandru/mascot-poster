# Targeted Image Pair Repair Design

## Goal

Replace broad two-sided image regeneration loops with one validator-directed repair that regenerates only the defective side, uses the accepted counterpart as a visual composition reference, and allows the video to continue when only minor cosmetic differences remain.

## Validation result

Pair validation will return the existing quality fields plus:

- `repair_side`: `left`, `right`, `both`, or `none`.
- `repair_instructions`: a short list of concrete visual corrections for image generation.
- `fatal_reasons`: wrong identity, unwanted text, prohibited content, unusable background, or clearly non-photorealistic imagery.
- `warning_reasons`: minor differences in scale, position, crop, lighting, shadows, or other photographic styling.

The validator prompt must never reject a pair because the compared products have different colors unless matching color is explicitly required by the paired brief.

## One-shot repair flow

The initial pair is validated once. If repair is required, the service preserves every acceptable side and performs exactly one repair generation:

- `left`: regenerate only the left image and pass the right image as a reference.
- `right`: regenerate only the right image and pass the left image as a reference.
- `both`: generate a single paired wide composition and split it into left and right assets, avoiding two independent calls.
- `none`: perform no generation.

After normalization, the repaired pair is validated once. No further image generation is allowed for that pair.

## Repair prompt

The repair prompt will include the full structured brief, the validator’s concrete corrections, and a detailed visual contract. It will instruct Gemini to preserve the requested identity and distinguishing material cues while matching the reference image’s object scale, visible bounding-box size, vertical center, camera elevation, perspective, crop, lighting direction, shadow softness, and background treatment. It will explicitly prohibit copying the reference object’s identity, material, color, labels, text, or product-specific details.

For unwanted text, the prompt will state that every visible surface must be blank and unbranded, including embossed, printed, engraved, stitched, overlaid, captioned, or watermark text. Different product colors remain allowed unless the brief explicitly requires a match.

## Image provider interface

The image provider will accept optional input-reference paths. OpenRouter requests will encode those images in `input_references`, using the capability already supported by the configured Gemini image endpoint. Existing providers and test doubles may omit references without breaking the base generation path.

## Final decision policy

After the single repair:

- Fail the job for wrong identity, unwanted or unrelated text, prohibited content, unusable background, or clearly fake/non-photorealistic output.
- Continue with warnings for residual scale, vertical-position, crop, lighting, shadow, or stylistic mismatch.
- Store the initial validation, repair instructions, repaired-side provenance, final validation, and warnings in image provenance and the quality report.

## Tests

Tests will verify repair-side classification, preservation of the accepted side, one-call maximum, input-reference encoding, complex repair-prompt content, two-sided paired generation behavior, fatal-versus-warning policy, color-difference tolerance, provenance, and the absence of any second repair loop.
