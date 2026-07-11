# AGENTS.md

## Project

Automated short-form comparison video generation platform (TikTok, YouTube Shorts, Instagram Reels).
Phase 1: Deterministic renderer — builds vertical 1080x1920 30fps videos from a JSON spec using
Pillow (frame composition) and FFmpeg (video assembly + audio muxing).
Phase 2: TTS integration — ElevenLabs provider, word/sentence timing, audio mixing, subtitle generation.
Phase 3: LLM script and scene generation — structured script schema, prompt templates, topic generation,
script validation with repair loop, scene planning with pose selection.
Phase 4: Research and verification — search provider, page extraction, research package, source storage,
claim verification with risk-based thresholds.
Phase 5: Image generation — cloud image provider, image normalization, caching, asset validation.
Phase 6: API and job queue — FastAPI endpoints, quality validation, cost tracking, error handling,
stage checkpoints, logging, debug bundle.
Phase 7: n8n orchestration — webhook service, notification service (Telegram/Discord/Slack),
approval flow, n8n workflow JSONs.
Phase 8: Publishing and analytics — TikTok/YouTube/Instagram adapters, analytics snapshots,
Docker Compose deployment, Dockerfile.

## Key commands

```bash
# Install package (editable + dev deps)
pip install -e ".[dev]"

# Generate placeholder mascot PNGs, sample images, narration audio, sample scene JSON
python scripts/generate_fixtures.py

# Validate mascot assets and template safe zones
python scripts/validate_assets.py

# Render a sample video from tests/fixtures/render_sample.json
python scripts/render_sample.py
python scripts/render_sample.py --spec path/to/spec.json --output path/to/output_dir
python scripts/render_sample.py --verbose

# Render with TTS-generated narration (requires ELEVENLABS_API_KEY)
python scripts/render_sample.py --spec tests/fixtures/render_tts_sample.json --tts --voice-id <id>

# Run all unit tests
python -m pytest tests/ -v

# Start the FastAPI server
uvicorn app.main:app --reload
```

## Architecture

- `src/app/domain/` — enums, Pydantic models (SceneSpec, RenderSpec, RenderResult, TTSSettingsSpec,
  ScriptPackage, Claim, ScenePlan, TopicCandidate, TopicSpec, ResearchPackage, ResearchFact,
  SourceReference, VerificationResult, ClaimVerification, CostRecord), exceptions
- `src/app/config.py` — typed settings (pydantic-settings), paths to assets/templates/fonts
- `src/app/rendering/` — compositor (Pillow), ffmpeg runner, timeline, coordinates, safe_zones,
  text_layout, transitions
- `src/app/providers/tts/` — TTSProvider protocol, TTSSettings, TTSResult, ElevenLabsProvider
  (httpx + tenacity retry + caching)
- `src/app/providers/llm/` — LLMProvider protocol, OpenAIProvider (structured JSON output,
  repair loop, cost tracking)
- `src/app/providers/search/` — SearchProvider protocol, TavilyProvider, SerperProvider
  (httpx + tenacity retry)
- `src/app/providers/images/` — ImageProvider protocol, OpenAIImageProvider, RemoteImageProvider
- `src/app/providers/storage/` — StorageProvider protocol, LocalStorageProvider, S3StorageProvider
- `src/app/prompts/` — topic_generation.md, script_generation.md, scene_planning.md,
  caption_generation.md, research_synthesis.md, fact_check.md
- `src/app/services/` — render_service, mascot_service, alignment_service, subtitle_service,
  audio_service, topic_service, script_service, scene_planner, script_helpers, research_service,
  fact_check_service, image_service, quality_service, cost_tracker, pipeline, notification_service,
  n8n_service, publishing_service, analytics_service
- `src/app/api/` — FastAPI routes (jobs, topics, render, approve/reject, cost, publish, analytics)
- `templates/comparison_v1.json` — layout regions, safe zones, font config, focus highlight
- `scripts/` — generate_fixtures.py, render_sample.py, validate_assets.py
- `n8n/workflows/` — generate_video.json, approval_flow.json, publish_video.json, analytics_collection.json
- `tests/unit/test_rendering.py` — 33 unit tests covering rendering logic
- `tests/unit/test_tts.py` — 22 unit tests covering TTS, alignment, subtitle, audio services
- `tests/unit/test_script.py` — 37 unit tests covering script schema, topic service, script service, scene planner
- `tests/unit/test_research.py` — 32 unit tests covering research models, source scoring, fact verification
- `tests/unit/test_platform.py` — 38 unit tests covering image service, storage, cost tracker, quality,
  notification, publishing, analytics, pipeline

## Conventions

- No comments in source code unless explicitly asked.
- Use type hints throughout.
- Use Pydantic models for all structured data.
- Keep every external provider behind an interface.
- Pass FFmpeg arguments as a list, never shell-interpolated.
- Secrets only in environment variables.
