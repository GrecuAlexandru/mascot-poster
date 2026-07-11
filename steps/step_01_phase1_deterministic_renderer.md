# Step 1 — Phase 1: Deterministic Renderer

> Goal of this step: prove the visual engine. Everything is fixed/hand-provided
> (topic, images, mascot, narration, scene JSON). The deliverable is a rendered
> 60-second vertical video from static inputs.

Sections in this step:

- [Phase 1 milestone](#phase-1-deterministic-renderer)
- [5. Repository Structure](#5-repository-structure)
- [6. Core Data Models](#6-core-data-models)
- [7. Configuration](#7-configuration)
- [14. Mascot Asset System](#14-mascot-asset-system)
- [18. Video Template](#18-video-template)
- [19. Rendering Strategy](#19-rendering-strategy)
- [21. Subtitle and Text Rendering](#21-subtitle-and-text-rendering)
- [34. Suggested First Implementation Task](#34-suggested-first-implementation-task)

---

## Phase 1: Deterministic renderer

Build first:

- Fixed topic
- Fixed images
- Fixed mascot
- Fixed narration
- Fixed scene JSON
- Render complete 60-second video

Deliverable:

```bash
python scripts/render_sample.py
```

This phase proves the visual engine.

---

## 5. Repository Structure

```text
automated-short-video-platform/
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── alembic.ini
│
├── src/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── logging.py
│       ├── dependencies.py
│       │
│       ├── api/
│       │   ├── routes_jobs.py
│       │   ├── routes_topics.py
│       │   ├── routes_assets.py
│       │   ├── routes_approvals.py
│       │   ├── routes_analytics.py
│       │   └── schemas.py
│       │
│       ├── db/
│       │   ├── base.py
│       │   ├── session.py
│       │   ├── models/
│       │   │   ├── channel.py
│       │   │   ├── topic.py
│       │   │   ├── research_source.py
│       │   │   ├── generation_job.py
│       │   │   ├── scene.py
│       │   │   ├── asset.py
│       │   │   ├── publication.py
│       │   │   └── analytics_snapshot.py
│       │   └── repositories/
│       │       ├── topics.py
│       │       ├── jobs.py
│       │       ├── assets.py
│       │       └── publications.py
│       │
│       ├── domain/
│       │   ├── enums.py
│       │   ├── exceptions.py
│       │   ├── models.py
│       │   └── validators.py
│       │
│       ├── services/
│       │   ├── topic_service.py
│       │   ├── research_service.py
│       │   ├── fact_check_service.py
│       │   ├── script_service.py
│       │   ├── scene_planner.py
│       │   ├── image_service.py
│       │   ├── mascot_service.py
│       │   ├── tts_service.py
│       │   ├── alignment_service.py
│       │   ├── subtitle_service.py
│       │   ├── audio_service.py
│       │   ├── render_service.py
│       │   ├── thumbnail_service.py
│       │   ├── quality_service.py
│       │   ├── storage_service.py
│       │   └── analytics_service.py
│       │
│       ├── providers/
│       │   ├── llm/
│       │   │   ├── base.py
│       │   │   ├── openai_provider.py
│       │   │   └── schemas.py
│       │   ├── tts/
│       │   │   ├── base.py
│       │   │   ├── elevenlabs_provider.py
│       │   │   └── openai_provider.py
│       │   ├── images/
│       │   │   ├── base.py
│       │   │   ├── openai_provider.py
│       │   │   └── remote_image_provider.py
│       │   ├── search/
│       │   │   ├── base.py
│       │   │   ├── tavily_provider.py
│       │   │   └── serper_provider.py
│       │   └── storage/
│       │       ├── base.py
│       │       ├── local_provider.py
│       │       └── s3_provider.py
│       │
│       ├── rendering/
│       │   ├── compositor.py
│       │   ├── ffmpeg.py
│       │   ├── timeline.py
│       │   ├── coordinates.py
│       │   ├── safe_zones.py
│       │   ├── transitions.py
│       │   ├── text_layout.py
│       │   └── templates/
│       │       ├── base.py
│       │       ├── comparison_v1.py
│       │       └── myth_vs_fact_v1.py
│       │
│       ├── prompts/
│       │   ├── topic_generation.md
│       │   ├── research_synthesis.md
│       │   ├── script_generation.md
│       │   ├── fact_check.md
│       │   ├── scene_planning.md
│       │   └── caption_generation.md
│       │
│       ├── workers/
│       │   ├── celery_app.py
│       │   ├── tasks_generation.py
│       │   ├── tasks_rendering.py
│       │   └── tasks_analytics.py
│       │
│       └── utils/
│           ├── files.py
│           ├── hashing.py
│           ├── retries.py
│           ├── timing.py
│           └── text.py
│
├── assets/
│   ├── mascots/
│   │   └── default/
│   │       ├── neutral.png
│   │       ├── point_left.png
│   │       ├── point_right.png
│   │       ├── point_up.png
│   │       ├── point_down.png
│   │       ├── arms_open.png
│   │       ├── thinking.png
│   │       ├── surprised.png
│   │       ├── warning.png
│   │       └── thumbs_up.png
│   ├── music/
│   ├── sound_effects/
│   ├── fonts/
│   └── backgrounds/
│
├── templates/
│   ├── comparison_v1.json
│   ├── comparison_v2.json
│   └── myth_vs_fact_v1.json
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── rendering/
│   └── fixtures/
│
├── scripts/
│   ├── seed_database.py
│   ├── render_sample.py
│   ├── validate_assets.py
│   └── export_debug_bundle.py
│
└── n8n/
    ├── workflows/
    │   ├── generate_video.json
    │   ├── approval_flow.json
    │   ├── publish_video.json
    │   └── analytics_collection.json
    └── README.md
```

---

## 6. Core Data Models

## Channel

Represents one content channel.

```python
class Channel:
    id: UUID
    name: str
    language: str
    niche: str
    enabled: bool
    mascot_set: str
    voice_provider: str
    voice_id: str
    template_name: str
    target_duration_seconds: int
    posts_per_day: int
    default_hashtags: list[str]
```

Example channels:

- Romanian food facts
- English product comparisons
- Romanian technology facts
- English myth versus fact

---

## Topic

```python
class Topic:
    id: UUID
    channel_id: UUID
    title: str
    comparison_left: str
    comparison_right: str
    angle: str
    status: TopicStatus
    priority: int
    source_hint: str | None
    created_at: datetime
```

Possible topic statuses:

```text
IDEA
RESEARCHING
RESEARCHED
APPROVED
SCRIPTED
RENDERED
PUBLISHED
REJECTED
FAILED
```

---

## Research source

```python
class ResearchSource:
    id: UUID
    topic_id: UUID
    url: str
    title: str
    publisher: str
    extracted_text: str
    retrieved_at: datetime
    trust_score: float
```

---

## Generation job

```python
class GenerationJob:
    id: UUID
    channel_id: UUID
    topic_id: UUID
    status: JobStatus
    current_stage: str
    error_message: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    output_video_url: str | None
    preview_url: str | None
    caption: str | None
```

Possible job statuses:

```text
QUEUED
RUNNING
WAITING_FOR_APPROVAL
APPROVED
REJECTED
PUBLISHING
PUBLISHED
FAILED
```

---

## Script package

The script should always be returned as validated structured data.

```python
class ScriptPackage(BaseModel):
    title: str
    hook: str
    narration_text: str
    caption: str
    hashtags: list[str]
    claims: list["Claim"]
    scenes: list["ScenePlan"]
    estimated_duration_seconds: float
```

---

## Claim

```python
class Claim(BaseModel):
    id: str
    text: str
    supporting_source_ids: list[str]
    confidence: float
    risk_level: Literal["low", "medium", "high"]
```

---

## Scene plan

```python
class ScenePlan(BaseModel):
    index: int
    narration: str
    duration_hint_seconds: float
    mascot_pose: str
    focus: Literal["left", "right", "both", "neutral"]
    on_screen_phrases: list[str]
    transition: str
    image_motion: str
    emphasis: list[str]
```

---

## 7. Configuration

Use environment variables and typed settings.

Example `.env.example`:

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg://app:app@postgres:5432/app
REDIS_URL=redis://redis:6379/0

OPENAI_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID_RO=
ELEVENLABS_VOICE_ID_EN=

SEARCH_API_KEY=
SEARCH_PROVIDER=tavily

S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=
S3_PUBLIC_BASE_URL=

N8N_WEBHOOK_URL=
INTERNAL_API_TOKEN=

DEFAULT_VIDEO_WIDTH=1080
DEFAULT_VIDEO_HEIGHT=1920
DEFAULT_VIDEO_FPS=30
DEFAULT_AUDIO_SAMPLE_RATE=44100
```

Secrets must not be stored in Git.

---

## 14. Mascot Asset System

The mascot should be a reusable asset set.

Each pose must:

- Be a transparent PNG
- Use the same canvas size
- Use the same character scale
- Use consistent lighting and style
- Have matching edges and color profile
- Be legally owned or licensed
- Work on light and dark backgrounds

Recommended initial poses:

```text
neutral
point_left
point_right
point_up
point_down
arms_open
hands_up
thinking
surprised
warning
thumbs_up
```

Create a metadata file:

```json
{
  "set_name": "default_mascot",
  "canvas_width": 1024,
  "canvas_height": 1024,
  "poses": {
    "neutral": "neutral.png",
    "point_left": "point_left.png",
    "point_right": "point_right.png"
  }
}
```

Validate at startup that every configured pose exists.

---

## 18. Video Template

Default output:

```text
Width: 1080
Height: 1920
Frame rate: 30 fps
Codec: H.264
Pixel format: yuv420p
Audio: AAC
Sample rate: 44.1 kHz or 48 kHz
Container: MP4
```

### Recommended layout

```text
Top safe margin

Title / hook

Left label          Right label

Left image          Right image

Dynamic highlighted phrase

Mascot

Bottom safe margin for platform UI
```

### Safe zones

Avoid placing essential content:

- Too close to the top edge
- Too close to the right edge where TikTok controls appear
- Too close to the bottom where captions and navigation appear

All coordinates should be defined in a template configuration file, not hard-coded throughout the application.

Example:

```json
{
  "canvas": {
    "width": 1080,
    "height": 1920
  },
  "regions": {
    "title": [80, 80, 920, 180],
    "left_image": [80, 280, 430, 620],
    "right_image": [570, 280, 430, 620],
    "phrase": [100, 930, 880, 180],
    "mascot": [180, 1080, 720, 720]
  }
}
```

---

## 19. Rendering Strategy

Use Pillow to generate static scene frames and FFmpeg to assemble them.

Avoid relying entirely on MoviePy.

### Rendering process

1. Create a frame for each scene
2. Draw background
3. Draw title
4. Draw labels
5. Draw comparison images
6. Add focus highlight
7. Draw current phrase
8. Add mascot pose
9. Save intermediate scene image
10. Use FFmpeg to hold the image for the scene duration
11. Add zoom or pan effect
12. Add transition
13. Concatenate scenes
14. Add voiceover
15. Add background music
16. Add sound effects
17. Normalize audio
18. Encode final MP4

### Motion effects

Use inexpensive motion:

- 2–4% zoom
- Slow pan
- Mascot fade
- Mascot scale-in
- Image pulse
- Highlight border
- Text pop
- Short crossfade
- Quick slide transition

Do not generate full AI animation unless a future format requires it.

---

## 21. Subtitle and Text Rendering

Use a font with Romanian diacritics.

Requirements:

- Large and readable
- High contrast
- Stroke or background box
- Maximum two lines
- Avoid very long phrases
- Consistent capitalization
- No text behind platform controls
- Correct line wrapping
- Automatic font-size reduction when necessary

Test:

- `ă`
- `â`
- `î`
- `ș`
- `ț`

Do not use OCR for validation. Validate against the known input text and layout bounds.

---

## 34. Suggested First Implementation Task

Start with a minimal vertical video renderer.

Input:

```json
{
  "title": "Vanilla sugar vs vanillin sugar",
  "left_label": "Vanilla sugar",
  "right_label": "Vanillin sugar",
  "left_image": "fixtures/left.png",
  "right_image": "fixtures/right.png",
  "audio": "fixtures/narration.mp3",
  "scenes": [
    {
      "start": 0.0,
      "end": 3.0,
      "pose": "point_up",
      "phrase": "THEY LOOK SIMILAR",
      "focus": "both"
    },
    {
      "start": 3.0,
      "end": 7.0,
      "pose": "point_left",
      "phrase": "NATURAL VANILLA",
      "focus": "left"
    }
  ]
}
```

Output:

```text
output/video.mp4
output/poster.jpg
output/contact-sheet.jpg
output/timeline.json
```

Only after this renderer works reliably should the model add LLMs, research, TTS, n8n, and publishing.
