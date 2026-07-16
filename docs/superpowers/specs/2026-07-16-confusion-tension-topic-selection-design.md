# Confusion-Tension Topic Selection Design

## Objective

Improve automatic topic selection so the generator prefers comparisons that viewers commonly confuse, debate, misuse interchangeably, or want to share with someone else. A topic must still be visually producible and factually researchable, but visual contrast alone is no longer sufficient.

The production pipeline and the `/api/v1/topics/generate` endpoint must use the same deterministic selection policy. Manual topic overrides remain unchanged.

## Current Problem

The API path requests multiple topic candidates but preserves model order after deduplication. The production pipeline requests exactly one candidate and accepts it immediately. Both prompts favor visually distinct physical objects, which can produce technically valid but obvious comparisons with little curiosity or sharing tension.

This design separates creative candidate generation from deterministic candidate selection. The language model proposes and explains several alternatives; application code enforces minimum standards, scores them consistently, and selects the strongest eligible topic.

## Candidate Data Model

`TopicCandidate` will retain its current fields and gain an optional structured `selection_signals` object. Both automatic-generation prompts require the object, while the optional default preserves compatibility for manual construction and older stored data. The automatic selector rejects a candidate whose signals are missing; it never invents neutral scores.

`TopicSelectionSignals` contains seven integer scores from zero through five and a short evidence string for each score:

- `common_confusion`: how often ordinary viewers confuse the names, identities, meanings, or uses of the two items.
- `everyday_familiarity`: how recognizable and relevant the pair is to the target audience.
- `cultural_debate`: strength of Romanian regional, linguistic, household, or cultural disagreement around the pair.
- `surprising_payoff`: strength of the verified factual correction or reveal available to the episode.
- `shareability`: likelihood that a viewer will send the comparison to someone or use it to settle a disagreement.
- `visual_feasibility`: how clearly two still images can establish the comparison within the fixed layout.
- `research_risk`: difficulty and potential harm of researching and stating the distinction correctly. A higher value is worse.

Each score uses a `TopicSignal` value with:

- `score`: integer from zero through five.
- `reason`: concise evidence tied specifically to the proposed pair, not generic praise.

Application code will reject malformed values through Pydantic validation. Prompt-generated candidates must provide all seven signals. Legacy candidates without signals can still be loaded but are not eligible for automatic selection.

## Eligibility Gates

A generated candidate is eligible only when all of these conditions hold:

- `max(common_confusion, cultural_debate) >= 3`. The pair needs genuine confusion or debate tension.
- `surprising_payoff >= 3`. The answer must contain a worthwhile correction or reveal.
- `visual_feasibility >= 3`. The fixed two-image format must communicate the pair clearly.
- `research_risk <= 3`. High-risk or difficult-to-substantiate ideas do not enter automatic production.
- `selection_signals` is present. Automatic selection never infers missing scores.
- The existing `risk_level` is not `high` unless a future caller explicitly opts into high-risk topics.
- The pair is not present in topic history in either left-right order.
- The pair is not duplicated elsewhere in the same candidate pool in either order.
- Neither item is blacklisted.

Candidates that fail a gate are removed rather than merely receiving a lower score. This prevents an attractive but unsuitable idea from winning through unrelated strengths.

## Weighted Ranking

Eligible candidates receive a deterministic editorial score with a maximum of 100 and a theoretical minimum of negative 10:

| Signal | Weight |
| --- | ---: |
| Common confusion | 25 |
| Surprising payoff | 20 |
| Shareability | 20 |
| Everyday familiarity | 15 |
| Cultural debate | 10 |
| Visual feasibility | 10 |
| Research risk | penalty of 10 |

Each positive signal contributes `score / 5 * weight`. Research risk subtracts `score / 5 * 10`. The result is rounded to two decimal places.

Ties are resolved deterministically in this order:

1. Higher common-confusion score.
2. Higher shareability score.
3. Higher surprising-payoff score.
4. Lower research-risk score.
5. Original candidate order.

The ranking service returns candidates in best-first order without mutating the input objects.

## Components

### Domain models

`src/app/domain/models.py` will define `TopicSignal` and `TopicSelectionSignals`, and extend `TopicCandidate` with `selection_signals`.

### Shared selector

`src/app/services/topic_selection_service.py` will contain `TopicSelectionService`. It will own:

- Eligibility evaluation.
- Weighted score calculation.
- Stable deterministic ranking.
- Pair normalization and reverse-pair duplicate handling.
- History and blacklist filtering for selection.

It will not call an LLM, read files, or persist state. This keeps selection cheap and directly testable.

### General topic service

`TopicService.generate_topics` will continue requesting a pool from the configured LLM. The topic prompt will require all seven scores and pair-specific reasons.

`TopicService.generate_unique_topics` will request an expanded pool, pass it through `TopicSelectionService`, and return at most the requested count in ranked order. The first result is therefore the best eligible topic rather than the model's first response.

### Production topic generator

`ReferenceTopicGenerator.generate` will request a structured pool rather than one `TopicCandidate`. A small response model will contain a `topics` list. The generator will request six candidates, apply the shared selector with history, and choose the first eligible result.

If the first pool contains no eligible candidate, it will make one repair attempt. The repair prompt will include compact rejection reasons and explicitly ask for candidates that clear the failed gates. If the repaired pool is also empty, generation fails with a clear error instead of silently accepting a weak topic.

Once selected, the winner is converted to `TopicSpec`, proofread as before, and added to history as before.

### API compatibility

The existing topic API response remains backward compatible. It will continue returning title, left, right, angle, why-it-might-work, and risk level. Internal signal details and the weighted score will not be added to the public response in this change.

## Prompt Policy

Both topic prompts will explain that a good comparison begins with confusion tension, not merely two visibly different objects. They will:

- Prefer commonly interchanged words, mistaken identities, regional disagreements, household myths, and distinctions that settle familiar arguments.
- Explicitly reject obvious-category pairs whose answer is already understood by nearly everyone.
- Require pair-specific reasons for every score.
- Calibrate zero as absent, three as meaningful, and five as unusually strong.
- Include Romanian examples such as vocabulary disputes, commonly confused foods, animals, materials, and household products without requiring the generator to reuse those exact pairs.
- Preserve visual, safety, factual, and no-duplicate constraints.

The prompts may propose concepts whose distinction is not visible from shape alone only when two clear representative images and on-screen labels can establish the comparison. Abstract topics that cannot be represented by two recognizable images remain excluded.

## Failure Handling

- Structurally invalid LLM candidates are skipped using the existing logging behavior.
- A pool with fewer valid candidates than requested returns the valid subset.
- A production pool with no eligible candidates triggers one bounded repair attempt.
- Two empty or ineligible production pools raise a descriptive `RuntimeError` containing the principal gate failures.
- High-risk topics remain excluded by default.
- Manual overrides bypass automatic scoring because the user has explicitly selected the topic.

## Testing

Unit tests will verify:

- Signal score bounds and required reasons.
- Weighted score calculation.
- Confusion-or-debate gate behavior.
- Payoff, visual-feasibility, and research-risk gates.
- High-risk exclusion.
- Reverse-pair and in-pool deduplication.
- Blacklist and history exclusion.
- Deterministic tie resolution.
- Ranked output from `TopicService.generate_unique_topics`.
- Production selection from a multi-candidate pool.
- One repair attempt when every initial candidate is ineligible.
- Clear failure after the repair pool is also ineligible.
- Manual topic overrides continuing to bypass selection.
- Existing topic, API, and pipeline tests remaining compatible.

## Non-Goals

This change will not:

- Train a statistical model from analytics.
- Add an additional LLM judge.
- Change research, script, image, rendering, publishing, or analytics behavior.
- Expose internal topic scores through the public API.
- Automatically rewrite user-supplied topic overrides.
- Guarantee view performance; it improves the editorial selection policy and makes it measurable.

## Future Extension

The deterministic score and individual signals create a stable feature record for a later analytics loop. Published share rate, save rate, completion rate, and follow conversion can eventually recalibrate weights or augment the selector without changing the candidate-generation contract.
