# AI Social Descriptions Design

## Goal

Generate a channel-specific Romanian TikTok description for every completed video, show that exact text in Telegram before approval, and send the approved text unchanged to Buffer.

The writing style is a playful expert: friendly, concise, concrete, lightly witty, and recognizable as Pufăilă without copying another creator's catchphrases.

## Chosen approach

Add a dedicated, checkpointed `social_description` model stage after `direction_tts` and before `compiled`.

This is preferable to expanding the existing script request because caption quality receives its own focused prompt and structured validation. It is preferable to generating during publication because Telegram must display the exact description that Buffer will receive.

The final narration can be rewritten during duration repair inside `direction_tts`. Running afterward guarantees the description is based on the final verified and timed script.

## Inputs and model

The description service receives:

- the comparison title and both object names;
- the final verified narration beats;
- the verified claims and available research facts;
- the episode language;
- a bounded list of recent generated descriptions for repetition avoidance.

The service uses the configured script LLM provider. Caption writing benefits from the stronger language model already selected for scripts, while avoiding another secret or required deployment setting.

The structured result contains:

```json
{
  "description": "Frigider vs congelator ❄️ ... Tu ce aliment pui mereu greșit? 🐹",
  "hashtags": ["pufaila", "stiaica", "bucatarie", "frigider", "congelator"]
}
```

## Description rules

For Romanian episodes, the model must:

1. Start with `X vs Y` and one relevant emoji.
2. Express one concrete, supported contrast rather than an abstract summary.
3. End with an easy personal-experience or preference question.
4. Use 25–45 words before hashtags, normally two or three short sentences.
5. Use correct Romanian diacritics and natural language.
6. Sound like a playful expert, not academic, corporate, or clickbait-driven.
7. Avoid copying `nu știam nici eu`, Nea Caisă's persona language, or any supplied reference wording.
8. Include only claims supported by the final verified script and research.
9. Return three to five hashtag tokens without `#`, spaces, or duplicates.
10. Always include the branded `pufaila` tag and the series tag `stiaica`, plus relevant category or object tags.

English episodes use the same structure in natural English, while retaining the `pufaila` and `stiaica` brand tags.

## Deterministic validation and formatting

A `SocialDescription` model owns the structured fields. The description service validates the word budget, required comparison opening, at least one question mark in the final sentence (allowing a trailing persona emoji), and non-empty hashtag list.

Hashtags are normalized outside the model:

- trim whitespace and a leading `#`;
- lowercase;
- fold Romanian diacritics to ASCII for stable search tags;
- remove spaces and unsupported punctuation;
- deduplicate while retaining order;
- force `pufaila` and `stiaica` into the first two positions;
- cap the final list at five;
- render each token with exactly one `#` only when composing the publishable caption.

The publishable text is:

```text
<description>

#pufaila #stiaica #category #left #right
```

No downstream component adds, removes, or regenerates words after this composition.

## Pipeline and checkpoints

The new `social_description` checkpoint stores the structured description and final publishable text. It is created after the final `direction_tts` script is stable and before rendering stages begin.

Checkpoint invalidation is:

- script regeneration: invalidate `social_description` and all existing script-dependent downstream stages;
- full regeneration: invalidate `social_description` with the full pipeline;
- image regeneration: preserve `social_description`, because the facts, narration, and topic are unchanged.

If generation or validation fails, the stage retries once with concise repair notes. If the second attempt fails, it falls back to the already AI-generated legacy script caption, applies the same deterministic hashtag normalization and required brand tags, and records `fallback_used: true` in the checkpoint. Description failure therefore cannot discard a completed video or force another narration/image purchase. Telegram still exposes the fallback text for human review before approval.

## Description history

Store a bounded history in `data/description_history.json`, mounted through the existing persistent data directory. Each entry contains only the topic title, description text, and creation timestamp—no credentials or personal information.

The model sees the latest ten descriptions and must vary opening modifiers, contrast rhythm, and engagement questions. History is capped at fifty entries. Both dedicated and fallback results enter history, while a repeated checkpoint does not append a duplicate entry.

## Telegram, approval, and Buffer

The automation worker reads `social_description.json`, not the legacy caption fields inside `script_verification.json`, and stores the composed publishable text in the automation job.

Telegram's existing review message therefore displays the exact description and hashtags before the user presses Approve. Approval locks the current video hash and current job caption. Buffer receives `job.caption` unchanged.

The script package retains its current `caption` and `hashtags` fields temporarily for compatibility with existing artifacts and tests, but automation publication no longer treats them as authoritative when a social-description checkpoint exists. A legacy fallback remains for old jobs without the new checkpoint.

Already submitted or published posts are not edited retroactively. The change applies to newly generated or regenerated jobs.

## Tests

Add coverage for:

- structured prompt inputs, Romanian tone rules, supported-fact rules, and anti-copy instruction;
- normalization, required brand tags, exact-one-`#` formatting, deduplication, and five-tag cap;
- description validation and one repair attempt;
- placement after final timing repair;
- checkpoint reuse and script/full/image invalidation behavior;
- bounded description history and duplicate suppression;
- worker preference for `social_description`, with legacy fallback;
- Telegram displaying the final publishable text;
- Buffer receiving the approved text unchanged.

Production acceptance generates one new candidate, checks the Telegram description, approves it only after user review, and verifies Buffer receives the same text byte-for-byte. Acceptance must not modify an already published post.
