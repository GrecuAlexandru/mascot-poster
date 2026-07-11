# Pose Direction, Narration Pacing, and Per-Job Cost Ledger Design

## Goal

Make the mascot expressive without changing its calibrated foot position, slow narration by approximately 20%, and produce a complete per-job cost report for every external provider call.

## Evidence from the Reviewed Render

The reviewed file `d9b13b125f738c6f367313e225ce973f.mp4` matches job `3deffa06-2aaf-4852-8ed3-2b755e78e6ae`. Its compiled direction contains 49 cues. Every cue selects the `neutral` pose, while anchors alternate between left, center, and right. The narration contains the requested deterministic pauses, but most body pauses are only 150–300 ms and the ElevenLabs voice speed is the default `1.0`.

The root causes are:

- The direction prompt permits one cue per word and does not require expressive pose diversity.
- There is no direction-plan quality validator or deterministic repair fallback.
- Anchor changes are used to communicate left and right focus, even though product focus can communicate this independently.
- Beat TTS uses the provider default speed instead of an explicit reference-workflow setting.
- The legacy `CostTracker` is not connected to the one-click reference pipeline or provider-call boundaries.

## Mascot Direction Contract

The mascot uses a stationary production pivot. All direction cues use `mascot_anchor=center`; comparison emphasis changes `product_focus` and the pose, not the mascot's position.

The desired comparison sequence is structurally equivalent to:

1. Hook: `intro_hands_up`, `surprised`, or `present_both`.
2. Left item: `point_left` or `point_up_left` with left product focus.
3. Pause or transition: hold the expressive pose, then optionally return to `neutral` at the next beat boundary.
4. Right item: `point_right` or `point_up_right` with right product focus.
5. Explanation: `explaining`, `thinking`, `idea`, `warning`, or `compare_left_right` according to meaning.
6. Conclusion: `thumbs_up`, `arms_crossed`, `celebrate`, or `outro_wave` according to the verdict.

Direction cues are beat-level. A beat normally receives one cue at its first meaningful word and may receive one additional cue only when focus changes inside the beat. The plan must not create a cue for every spoken word.

### Direction Validation

A `ReferenceDirectionValidator` validates and normalizes the LLM result before timing compilation. A valid plan must:

- anchor every pose at center;
- reference valid beat and word indexes;
- contain at least one non-neutral pose;
- use `point_left` or `point_up_left` for left-focused comparison beats;
- use `point_right` or `point_up_right` for right-focused comparison beats;
- contain no more than two cues per beat;
- avoid consecutive cues that produce no visual change;
- use `pose_pop` for pose changes, `focus_tick` for focus-only changes, and no whoosh for stationary pose swaps;
- leave at least 600 ms between sound effects after compilation.

If the LLM plan fails, the service makes one structured repair request with explicit validation problems. If the repaired result still fails, a deterministic beat-aware fallback constructs a valid expressive plan from beat order, item mentions, and the closing beat. Generation does not silently fall back to an all-neutral plan.

## Calibration Workflow

The existing `scripts/generate_mascot_calibration.py` remains the user-facing calibration command. It reads `assets/mascots/default/pose_calibration.json` and produces:

- one 1080×1920 PNG for every declared mascot pose;
- the same fixed magenta reference dot at `(540, 1670)` in every preview;
- a contact sheet;
- `calibration-index.json` with source paths and resolved pivots.

Each pose retains independent editable `x`, `y`, and `scale` values. Neutral, `point_left`, and `point_right` start with the same target foot pivot. The production renderer applies these calibrated values with a center anchor and never renders the reference dot. Changing from neutral to either pointing pose therefore swaps artwork around the same calibrated pivot instead of moving the mascot across the canvas.

## Narration Pacing

The one-click reference workflow passes `TTSSettings(speed=0.8)` to every ElevenLabs beat. The legacy rendering workflow retains its existing defaults.

Pauses remain deterministic silence inserted between synthesized beat files. Script generation should prefer 300–500 ms body pauses and a 750 ms closing pause, using 150 ms only for deliberately connected short phrases. Actual ElevenLabs timestamps remain the source of word timing after the speed change.

The existing 20–60 second narration quality gate remains in force. When slower speech exceeds 60 seconds, the existing script-repair loop shortens the narration and resynthesizes it. Captions, directions, sound effects, narration end, and CTA timing are recompiled from the new timestamps.

## Per-Job Cost Ledger

### Data Model

Each external call creates one `CostEvent` containing:

- stable event ID and job ID;
- UTC timestamp;
- pipeline stage;
- provider and model;
- operation name;
- input and output unit counts and unit types;
- amount in USD;
- `amount_kind`, either `actual` or `estimated`;
- pricing or provider source;
- request attempt number;
- success or failure status;
- optional cache-hit flag and normalized failure message.

Failed calls remain visible. They normally have a zero amount unless the provider reports a billed amount. Cache hits are recorded with zero incremental cost so the report explains why a stage did not incur another charge.

### Concurrency-Safe Collection

The one-click generator creates one `JobCostLedger` per job. A context-local cost scope carries the active job and stage through asynchronous provider calls, including parallel image acquisition. This avoids mutable global or shared-provider state and remains safe if API jobs run concurrently.

Providers and services record events at the boundary where complete usage information exists:

- OpenRouter text and vision completions use provider-reported `usage.cost` when present; otherwise they use the configured token-price estimate.
- Tavily or Serper search calls use provider-returned estimates or configured per-query estimates.
- Image downloads record zero API cost unless the search provider reports a cost attributed to the request.
- Every OpenRouter image-generation attempt records the provider-reported cost when available, otherwise the image-model estimate.
- Every ElevenLabs beat records characters and the provider result's estimated cost. It is labeled estimated because ElevenLabs does not provide an authoritative billed amount per synthesis response.
- Local FFmpeg rendering, locally generated SFX, and local storage are listed as zero-cost local operations, not external API expenses.

### Outputs

At the end of generation, the job directory contains `cost_report.json`. It includes every event plus totals grouped by provider, stage, operation, model, and amount kind. It also reports:

- total provider-reported actual cost;
- total estimated-only cost;
- combined projected job cost;
- counts of billable calls, failed calls, retries, generated images, searches, and TTS beats.

`RenderResult` exposes `cost_report_path`. Streamlit shows a concise cost summary after the video and a detailed table in diagnostics, with a download button for the JSON report. Currency values retain internal precision in JSON and use six decimal places in the detailed table.

Checkpoint retries load existing cost events and append only new calls. Event IDs prevent duplicate accounting when a completed stage is reused. A retry therefore shows the complete historical cost of producing that job, including failed and superseded attempts.

## Error Handling

- Invalid direction plans receive one repair attempt and then deterministic fallback.
- Cost recording must never hide or replace the original provider error.
- A malformed provider usage payload becomes an estimated event with a recorded normalization note.
- Failure to persist the final ledger is a stage-specific generation failure because the cost report is a required artifact.
- Existing checkpoints without a cost ledger start with an empty ledger and remain readable.

## Testing and Acceptance

Unit coverage will verify:

- stationary center anchors across neutral and pointing pose changes;
- expressive pose diversity and cue-count limits;
- direction repair and deterministic fallback;
- `speed=0.8` reaching every ElevenLabs call;
- pause offsets and word timing remaining correct at slower speed;
- actual-versus-estimated OpenRouter accounting;
- per-beat ElevenLabs events;
- image retry and failed-call accounting;
- cache-hit and checkpoint-resume deduplication;
- totals grouped by provider, stage, operation, model, and amount kind;
- Streamlit exposure of the cost report.

The acceptance render must show neutral, left-pointing, and right-pointing poses sharing the same calibrated foot pivot; contain no left/right anchor travel; speak at `0.8` speed with audible beat pauses; retain exact word-aligned captions; keep narration within 20–60 seconds; and expose a complete downloadable cost report.

## Compatibility

Legacy `RenderSpec`, API, publishing, analytics, and n8n behavior remain unchanged. The new pacing and direction rules apply only to the one-click reference workflow. The existing `CostTracker` API may delegate to the new ledger for compatibility, but existing callers and response schemas remain valid.
