# Automated TikTok Comparison Channel — Implementation Plan (Split)

This folder splits the original master plan
(`../automated_tiktok_channel_implementation_plan.md`) into 8 buildable phases so
the work is not tackled all at once. Each `step_0X_*.md` file contains only the
sections relevant to that phase, plus the phase milestone from Section 31.

> The original file is kept untouched as the single source of truth. These split
> files are a convenience for working phase by phase.

---

## Roadmap / Steps

| Step | Phase | Focus | Deliverable |
|------|-------|-------|-------------|
| 1 | Phase 1 — Deterministic renderer | Fixed topic, images, mascot, narration, scene JSON → 60s video | `python scripts/render_sample.py` |
| 2 | Phase 2 — TTS integration | ElevenLabs, RO/EN voices, caching, timing, audio mixing | Narration from text → rendered video |
| 3 | Phase 3 — LLM script & scene generation | Script schema, prompts, validation, scene planning, captions | Topic → complete script package |
| 4 | Phase 4 — Research & verification | Search, page extraction, research package, claim verification | Script grounded in stored sources |
| 5 | Phase 5 — Image generation | Cloud image provider, normalization, caching, asset validation | Two comparison images auto-generated |
| 6 | Phase 6 — API & job queue + safeguards | FastAPI, Postgres, worker queue, endpoints, cost, error handling, logging, quality gates | Jobs triggered remotely |
| 7 | Phase 7 — n8n orchestration | Schedule, completion webhook, Telegram/Discord approval, publish workflow, failure alerts | End-to-end generation with human approval |
| 8 | Phase 8 — Publishing & analytics | TikTok/YouTube/Reels posting, analytics snapshots, deployment, definition of done | Multi-platform publishing & tracking |

### Cross-cutting sections (this file)

The sections below apply across all phases, so they live here in the index rather
than being repeated in every step file.

1. [Project Goal](#1-project-goal)
2. [Core Architectural Principle](#2-core-architectural-principle)
3. [Recommended Technology Stack](#3-recommended-technology-stack)
4. [High-Level Workflow](#4-high-level-workflow)
5. [Testing Strategy](#28-testing-strategy)
6. [Security](#29-security)
7. [Important Implementation Rules for the Coding Model](#33-important-implementation-rules-for-the-coding-model)
8. [Final Expected User Experience](#35-final-expected-user-experience)

---

## 1. Project Goal

Build a production-ready application that automatically creates and publishes short-form comparison videos for TikTok, YouTube Shorts, Instagram Reels, and similar platforms.

The target format is:

- Vertical 9:16 video
- Usually 30–90 seconds
- Two comparison images near the top
- A reusable mascot character in the lower half
- The mascot changes between a small set of static poses
- A text-to-speech voice narrates the script
- Short words or phrases appear on screen in sync with the narration
- Small transitions, zooms, fades, and sound effects create movement
- Videos are generated automatically from structured data
- n8n handles scheduling, approvals, publishing, notifications, and analytics orchestration
- Python handles research, script generation, asset processing, text-to-speech, timing, rendering, validation, and metadata generation

The first implementation should prioritize:

1. Reliability
2. Reproducibility
3. Low recurring cost
4. Easy debugging
5. Modular services
6. Human approval before publishing
7. Future support for multiple channels and languages

---

## 2. Core Architectural Principle

Use **Python as the production engine** and **n8n as the orchestration layer**.

### Python is responsible for

- Topic selection
- Research collection
- Fact extraction
- Script generation
- Claim verification
- Scene planning
- Text-to-speech
- Word and sentence timing
- Image generation or image retrieval
- Image cleanup and normalization
- Mascot pose selection
- Subtitle generation
- Video rendering
- Audio mixing
- Thumbnail generation
- Quality validation
- Exporting publish-ready files
- Preparing captions, hashtags, and source metadata
- Recording job state in the database

### n8n is responsible for

- Cron scheduling
- Triggering Python jobs
- Sending approval messages
- Waiting for approval or rejection
- Publishing to TikTok or a publishing service
- Posting to other platforms
- Sending alerts when jobs fail
- Collecting analytics
- Updating content status
- Re-running failed workflows
- Sending daily or weekly summaries

Do not put rendering logic, prompt logic, or complex business logic directly inside n8n nodes.

---

## 3. Recommended Technology Stack

### Main application

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- Redis
- Celery, Dramatiq, or RQ for background jobs
- FFmpeg
- ffprobe
- Pillow
- OpenCV only where useful
- httpx
- tenacity
- structlog or standard logging
- pytest
- Docker Compose

### External cloud services

Recommended initial choices:

- LLM: OpenAI API
- Text-to-speech: ElevenLabs
- Image generation: OpenAI Images or another cloud image provider
- Optional search/research API: Tavily, Serper, Brave Search, or a custom source collector
- Object storage: Cloudflare R2, Backblaze B2, S3, or MinIO
- Social publishing:
  - TikTok Content Posting API, or
  - Postiz / Upload-Post / similar service while validating the channel

### Orchestration

- Self-hosted n8n
- Webhook communication between n8n and FastAPI

---

## 4. High-Level Workflow

```text
n8n cron trigger
    ↓
POST /jobs/create
    ↓
Python creates generation job
    ↓
Choose or generate topic
    ↓
Research topic
    ↓
Extract facts and sources
    ↓
Generate script
    ↓
Verify factual claims
    ↓
Generate scene plan
    ↓
Generate or acquire images
    ↓
Normalize images
    ↓
Generate TTS narration
    ↓
Create timestamps
    ↓
Render video
    ↓
Run quality checks
    ↓
Upload output files to storage
    ↓
Notify n8n
    ↓
n8n sends approval preview
    ↓
Human approves or rejects
    ↓
n8n publishes
    ↓
Analytics are collected later
```

---

## 28. Testing Strategy

### Unit tests

Test:

- Script schema validation
- Topic deduplication
- Cost calculation
- Text wrapping
- Safe-zone calculations
- Scene timing
- Pose selection
- Caption generation
- Source scoring

### Integration tests

Test:

- OpenAI provider with mocked responses
- ElevenLabs provider with mocked responses
- Storage upload
- Database transactions
- End-to-end generation with fixtures

### Rendering tests

Create deterministic fixtures.

Verify:

- Output resolution
- Duration
- Frame count
- Audio stream
- Text boundaries
- Image placement
- Mascot placement
- No black frames

Store golden-image snapshots for selected frames.

### End-to-end smoke test

Command:

```bash
python scripts/render_sample.py
```

It should generate a complete test video without external research.

---

## 29. Security

- Protect internal API endpoints with a shared secret or JWT
- Verify n8n webhook signatures
- Never expose provider API keys to the browser
- Sanitize downloaded filenames
- Reject unsupported file types
- Limit download sizes
- Use timeouts
- Avoid shell interpolation
- Pass FFmpeg arguments as a list
- Store secrets only in environment variables
- Restrict storage bucket permissions
- Use signed URLs for private previews

---

## 33. Important Implementation Rules for the Coding Model

The implementation model should follow these rules:

1. Build the renderer before building the entire automation pipeline.
2. Keep every external provider behind an interface.
3. Use Pydantic schemas for every LLM output.
4. Never parse unstructured LLM prose when structured JSON can be required.
5. Make every pipeline stage independently retryable.
6. Save intermediate outputs.
7. Use FFmpeg directly for final rendering.
8. Use Pillow for frame composition.
9. Keep n8n workflows thin.
10. Do not put secrets in source code.
11. Write tests for all deterministic logic.
12. Use type hints throughout.
13. Use asynchronous HTTP clients for API calls.
14. Implement exponential backoff for external services.
15. Track API cost per job.
16. Preserve all factual sources.
17. Prevent duplicate topics and duplicate scripts.
18. Add a human approval step before initial production publishing.
19. Do not automate browser login to TikTok as the main publishing solution.
20. Use official APIs or a reputable publishing service.

---

## 35. Final Expected User Experience

The operator should be able to:

1. Open a dashboard or send a command
2. Choose a channel
3. Optionally enter a topic
4. Click Generate
5. Receive a preview automatically
6. Approve, reject, or regenerate
7. Let n8n publish at the scheduled time
8. Review performance and cost later

The normal production workflow should require less than one minute of human attention per video.
