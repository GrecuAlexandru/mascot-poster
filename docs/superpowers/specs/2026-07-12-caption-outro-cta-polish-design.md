# Caption, Outro, and CTA Polish Design

## Goal

Refine the reference-video presentation so captions read as one compact unit, active-word backgrounds sit naturally around the lettering, the Pufăilă sign-off is not rushed, and the final call to action has a deliberately bold visual presence.

## Captions

- Preserve the existing one-to-four-word caption groups and one- or two-row layouts.
- Reduce the horizontal gap between words from `0.52` to approximately `0.40` times the caption font size.
- Position the active-word background from the measured text bounding box rather than the drawing baseline so its visible padding is vertically balanced around the glyphs.
- Preserve the existing coral active background, yellow active text, white inactive text, dark outline, shadow, and word-timing behavior.
- Keep caption rows vertically centered within the configured caption region.

## Closing narration

- Keep the regular narration speed at `1.05`.
- Synthesize only the beat with id `closing` at approximately `0.88` speed.
- Keep the canonical Romanian closing text exactly `Vă pupă Pufăilă!` and retain the current pause after the closing beat.
- Continue providing the preceding beat as TTS context so the sign-off remains connected to the narration.
- Apply the slower setting per beat through the existing provider interface; do not post-process or splice the final word independently.
- Include the effective TTS settings in the request identity used for provider caching so old faster audio cannot be reused for the closing beat.

## Bold call to action

- Render the CTA text as `LIKE · SHARE · FOLLOW` while keeping the underlying default CTA content compatible with existing compiled specifications.
- Use a dark filled rounded card with a thick yellow border, white heavy text, and a stronger soft shadow.
- Keep the card centered above the mascot and constrained to the canvas margins.
- Preserve CTA visibility from the start of the closing beat through the end of the video.
- Retain the tail-free card shape and existing mascot outro pose behavior.

## Components

- `ReferenceRenderer` owns caption spacing, active-word background geometry, and the bold CTA card appearance.
- `BeatTTSService` derives effective settings for each beat and applies the closing-only speed override without changing other beats.
- The video generation pipeline continues to supply the regular narration settings once; it does not need a separate closing synthesis path.

## Testing and verification

- Add a renderer test that proves the configured word gap is tighter.
- Add a pixel or geometry-level test that proves the active background has balanced top and bottom padding around the text bounding box.
- Add CTA-card tests for dark fill, yellow border, uppercase display text, and the existing tail-free anchor.
- Add a beat TTS test that proves ordinary beats receive speed `1.05` and the closing beat receives approximately `0.88`.
- Prove each behavior with a failing test before implementation.
- Run the focused renderer and reference-pipeline tests, then the full unit test suite.
- Render representative caption and outro frames and inspect them for spacing, centering, clipping, contrast, and safe-zone placement.

## Non-goals

- Do not change caption grouping, font size, caption colors, product layout, mascot calibration, narration wording, or global narration pace.
- Do not modify provider APIs or add audio post-processing solely for the closing line.
