# Cut-Paper Captions and Memorable Script Line Design

## Objective

Improve the reference-video format in two coordinated ways:

1. Make captions feel like expressive, hand-arranged cut-paper typography rather than karaoke text with a single active-word highlight.
2. Make every generated episode contain one concise, memorable line that helps the audience retain and repeat the verified comparison.

The normal generation path will aim for roughly 30 seconds by default, but this work will add no 27–34-second enforcement, rejection rule, or duration quality gate. Explicit duration requests and the existing broad pipeline behavior remain supported.

## Scope

This design changes caption grouping and drawing, the structured reference-script contract, script prompting and repair, and focused production-quality checks for the memorable line. It does not redesign product reveals, image validation, research verification, TTS timing, mascot choreography, CTA behavior, or publishing.

## Caption Language

### Chunking

The timeline compiler will show one to three words in each visible caption chunk. The existing word-level timing remains authoritative: every `CaptionCue` still activates exactly one spoken word and begins at that word’s resolved TTS timestamp. Consecutive words share a chunk only when they fit within these limits:

- At most three words.
- At most 24 visible characters including spaces.
- A punctuation boundary or a pause of more than 300 milliseconds starts a new chunk.

The compiler will no longer create four-word chunks. Existing active-word sequence validation remains unchanged, so caption timing cannot drift from narration.

### Fixed visual system

Every visible word receives its own card. Cards cycle through a fixed three-color palette:

- Coral: `#E87560`
- Mustard: `#F2C14E`
- Mint: `#78C6A3`

All card text is dark brown-black `#241F1A`. Caption text has no white fill, heavy outline, or outlined shadow. The renderer may use a small soft card shadow to separate paper from the white canvas, but the glyphs themselves remain flat and dark.

The font starts at 118 pixels and may shrink only as needed to fit the caption region. Line height and inter-word gaps are tightened so the cards occupy more of the available vertical area. A three-word chunk may use one or two compact rows, but never more than two.

### Cut-paper shape and motion state

Each word card is rendered on its own transparent layer, then rotated by a deterministic angle selected from `-2`, `-1`, `1`, or `2` degrees. Rotation is derived from the normalized word and its position in the chunk using a stable digest, so identical inputs produce identical frames across processes.

The card uses a slightly irregular four-sided polygon instead of a rounded rectangle. Corner offsets are also deterministic and remain within six pixels, preserving readability and preventing visible jitter between frames.

The active spoken word receives a restrained emphasis:

- 1.06 scale.
- Six-pixel upward lift.
- No palette swap, outline, or glow.

Inactive cards remain fully visible. This preserves the excellent word timing while making the whole phrase readable and visually coherent.

### Layout safety

Cards are measured after rotation and centered as a group within the caption region. The renderer must keep every rotated card inside the region’s horizontal bounds and must not overlap the product labels or mascot. Long Romanian words shrink the shared chunk font rather than being clipped.

## Memorable Script Line

### Structured contract

`ReferenceScriptPackage` will gain a required `memory_device` object with:

- `kind`: one of `analogy`, `surprising_correction`, `humorous_contrast`, or `repeatable_sentence`.
- `line`: the exact spoken sentence, normalized for surrounding whitespace.
- `beat_id`: the ID of the narration beat containing that exact sentence.

The script model validates that:

- `line` contains 6–20 words.
- `beat_id` identifies exactly one non-hook, non-closing beat.
- The selected beat contains the exact memorable line as a complete sentence.
- The hook and mascot signoff cannot serve as the memory device.

The memory-device beat can also contain a short factual setup, but the memorable sentence itself must be intact so downstream validation and testing can find it deterministically.

### Factual grounding

A memory device may rephrase verified facts as an analogy or contrast, but it may not add a new measurable, medical, safety, financial, or causal claim. When the selected beat contains factual content, its existing `claim_ids` must point to the claims that support it. The current research verifier continues to decide whether those claims are grounded.

Examples of acceptable memory devices:

- Analogy: `Frigiderul pune mâncarea pe pauză; congelatorul aproape oprește filmul.`
- Surprising correction: `Nu culoarea face diferența, ci felul în care este construit.`
- Humorous contrast: `Unul vine la plimbare, celălalt vine pregătit de șantier.`
- Repeatable sentence: `Aceeași formă nu înseamnă aceeași treabă.`

The prompt explicitly instructs the model to use only a comparison supported by the supplied facts and to prefer a non-quantitative memory device.

### Generation and repair

The script-generation prompt will require exactly one `memory_device` and a dedicated beat containing its exact line. It will explain the four allowed types, include the refrigerator/freezer example as a structural example only, and prohibit copying example facts into unrelated topics.

After model output and bookend normalization, the service validates the memory-device contract through the Pydantic model. Malformed structured output follows the provider’s existing structured-output repair behavior. If later script verification requests factual changes, the regenerated script must produce a still-valid memory device from the repaired facts.

The proofreader may correct Romanian spelling and diacritics, but it must update both `memory_device.line` and the containing beat consistently. If it cannot preserve exact inclusion, the original unproofread script is retained by the existing proofreader safety behavior.

### Production quality evidence

Final reference quality checks will confirm that the compiled transcript contains the exact memory-device line in spoken order. This is not a semantic style classifier; it is a deterministic artifact-integrity check ensuring the structured line survived proofing, TTS, checkpointing, and compilation.

## Duration Behavior

The default `GenerationRequest.target_duration_seconds` changes from 25 to 30 seconds, and the script prompt describes this as an approximate pacing target. Word budgeting continues to derive from the requested target.

This work adds no new minimum or maximum, no 27–34-second acceptance window, no new TTS repair trigger, and no duration-based quality failure. A caller may still explicitly request any duration currently accepted by the API, including 20, 25, or 60 seconds. Existing broad duration safeguards are left unchanged rather than expanded.

Tests will compare representative 25-second and default 30-second prompt inputs and word budgets, but will not assert that rendered audio must land inside a new time window.

## Components and Data Flow

1. `ReferenceScriptService` requests a structured script with one memory device.
2. `ReferenceScriptPackage` validates the device type, length, beat reference, and exact sentence inclusion.
3. The proofreader preserves the beat/device pair as one consistency unit.
4. Research verification validates any factual claims attached to the memorable beat.
5. Beat TTS produces the same word timing used today.
6. `TimelineCompiler` groups timed words into one-to-three-word chunks while preserving one cue per active word.
7. `ReferenceRenderer` lays out one deterministic cut-paper card per visible word and applies the active-word lift and scale.
8. `ReferenceQualityService` confirms both caption-to-transcript identity and memory-device survival in the compiled transcript.

## Error Handling

- A script with a missing, duplicated, overlong, or incorrectly referenced memory device fails model validation and enters the existing structured-output repair path.
- A memory-device sentence that is not present exactly in its referenced beat fails validation.
- Unsupported factual content remains the responsibility of the existing claim verifier and repair loop.
- Caption layout shrinks the shared font to the configured minimum before failing; it never clips or silently drops a word.
- Deterministic card geometry uses no process-random state, preventing flicker and non-reproducible renders.
- Existing checkpoint payloads without `memory_device` are invalidated at script loading through normal model validation and must be regenerated rather than rendered with an incomplete contract.

## Testing Strategy

### Domain and script tests

- Accept each of the four memory-device kinds.
- Reject missing beat references, hook/closing references, lines outside 6–20 words, and lines absent from the selected beat.
- Verify the prompt requires exactly one grounded memory device.
- Verify bookend enforcement leaves the memory-device beat and metadata synchronized.
- Verify Romanian proofing preserves exact line inclusion.
- Verify default duration becomes 30 while explicit 20-, 25-, and 60-second requests remain accepted.
- Verify no new 27–34-second duration gate exists.

### Timeline tests

- Compile one-, two-, and three-word caption chunks.
- Split at the fourth word, punctuation, character limit, and pauses over 300 milliseconds.
- Preserve the exact active-word sequence and resolved word timing.

### Renderer tests

- Every visible word has a coral, mustard, or mint card.
- Text is dark and has no white outline.
- Card rotation and corner offsets are deterministic and bounded.
- Active cards use 1.06 scale and a six-pixel lift.
- Long Romanian chunks remain inside the caption region at the largest fitting shared font.
- Captions use more of the region vertically without overlapping adjacent regions.

### Pipeline and quality tests

- Structured memory-device metadata survives checkpoint serialization.
- Final quality rejects a compiled artifact whose spoken transcript lost or changed the exact memory-device line.
- Existing research, TTS, renderer, and full repository suites remain green.

## Acceptance Criteria

- Captions contain one to three visible words per chunk.
- Every visible word sits on an individual deterministic coral, mustard, or mint cut-paper card.
- Caption glyphs are dark with no heavy white outline.
- The active word has only the defined scale-and-lift emphasis.
- Every generated reference script contains exactly one valid structured memory device in a dedicated beat.
- The memorable line is grounded through existing claims and survives into the compiled spoken transcript.
- Default generation guidance is approximately 30 seconds without any new duration enforcement.
- Explicit existing duration requests remain valid.
- Focused and full automated tests pass.
