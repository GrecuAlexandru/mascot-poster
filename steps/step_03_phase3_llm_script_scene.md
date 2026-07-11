# Step 3 — Phase 3: LLM Script and Scene Generation

> Goal of this step: turn a topic into a complete, validated `ScriptPackage`
> (strict JSON) including the scene plan. Manual topic input is supported, and
> automated topic generation is introduced here.

Sections in this step:

- [Phase 3 milestone](#phase-3-llm-script-and-scene-generation)
- [9. Topic Generation](#9-topic-generation)
- [11. Script Generation](#11-script-generation)
- [13. Scene Planning](#13-scene-planning)

---

## Phase 3: LLM script and scene generation

Add:

- Structured script schema
- Prompt templates
- Script validation
- Scene planning
- Caption generation
- Repair loop for invalid JSON

Deliverable:

- Topic input becomes complete script package

---

## 9. Topic Generation

The topic service should support two modes.

### Manual topic mode

The user enters:

```json
{
  "left": "zahăr vanilat",
  "right": "zahăr vanilinat",
  "angle": "diferența de ingrediente"
}
```

### Automatic topic mode

The LLM generates candidate topics based on:

- Channel niche
- Language
- Previously published topics
- Topic blacklist
- High-performing historical topics
- Seasonal context
- Search trends
- Product categories
- Audience questions

The LLM should return 10–20 candidates.

Each candidate should contain:

```json
{
  "title": "Unt vs margarină",
  "left": "unt",
  "right": "margarină",
  "angle": "diferența dintre grăsimi și procesare",
  "why_it_might_work": "common confusion and strong visual comparison",
  "risk_level": "medium"
}
```

Before inserting a new topic:

- Compare it against existing topics using normalized text
- Compare semantic similarity using embeddings if needed
- Reject near-duplicates
- Reject topics that require medical or legal claims unless explicitly allowed
- Reject topics without reliable sources

---

## 11. Script Generation

The script generation model should receive:

- Channel style
- Language
- Target duration
- Research package
- Allowed facts
- Forbidden claims
- Previous scripts for duplication avoidance
- Available mascot poses
- Template constraints

The output must be strict JSON validated by Pydantic.

### Script rules

- Target 130–180 spoken words for approximately 60 seconds
- Hook in the first 1–2 seconds
- Keep sentences short
- Avoid excessive filler
- Explain one idea at a time
- Mention both sides clearly
- Include a practical conclusion
- End with a natural engagement question
- Avoid unsupported absolutes
- Avoid fake urgency
- Avoid repeating the same hook format every time
- Keep language natural for the target locale
- Do not include citations in narration
- Keep source references in metadata

### Romanian style guidance

- Natural conversational Romanian
- Avoid literal English translations
- Correct diacritics
- Avoid overly formal wording
- Avoid unnatural marketing phrases
- Use short spoken sentences
- Confirm pronunciation of foreign product names

### English style guidance

- Energetic and conversational
- Avoid generic AI phrasing
- Keep claims simple
- Prefer active voice
- Use vocabulary suitable for short-form educational content

---

## 13. Scene Planning

The scene planner converts the verified script into visual scenes.

Each scene should normally last 1–4 seconds.

The planner decides:

- Mascot pose
- Left, right, both, or neutral focus
- On-screen phrase
- Image emphasis
- Transition type
- Zoom direction
- Sound effect placement
- Optional color highlight

Example:

```json
{
  "index": 3,
  "narration": "Zahărul Bourbon conține vanilie naturală.",
  "mascot_pose": "point_left",
  "focus": "left",
  "on_screen_phrases": [
    "VANILIE NATURALĂ"
  ],
  "transition": "quick_fade",
  "image_motion": "slow_zoom_in",
  "emphasis": [
    "Bourbon",
    "naturală"
  ]
}
```

### Pose selection rules

- `point_left` when discussing the left image
- `point_right` when discussing the right image
- `point_up` for general facts or titles
- `thinking` before a surprising fact
- `surprised` for a reveal
- `warning` for an important limitation
- `arms_open` when comparing both sides
- `thumbs_up` for final conclusion

Avoid switching poses more often than every 0.6 seconds.
