# Step 6 — Phase 6: API and Job Queue + Safeguards

> Goal of this step: make jobs triggerable remotely via FastAPI, persisted in
> PostgreSQL, and processed by a worker queue. This step also bundles the
> pipeline-integrity concerns that live in the job system: cost tracking, error
> handling/idempotency, logging/observability, and automated quality validation.

Sections in this step:

- [Phase 6 milestone](#phase-6-api-and-job-queue)
- [8. Python API Design](#8-python-api-design)
- [22. Quality Validation](#22-quality-validation)
- [23. Cost Tracking](#23-cost-tracking)
- [26. Error Handling](#26-error-handling)
- [27. Logging and Observability](#27-logging-and-observability)

---

## Phase 6: API and job queue

Add:

- FastAPI
- PostgreSQL
- Worker queue
- Job status endpoints
- Retry endpoints
- Storage integration

Deliverable:

- Jobs can be triggered remotely

---

## 8. Python API Design

Use FastAPI.

### Create a generation job

```http
POST /api/v1/jobs
```

Request:

```json
{
  "channel_id": "uuid",
  "topic_id": "uuid-or-null",
  "auto_select_topic": true
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "QUEUED"
}
```

### Get job status

```http
GET /api/v1/jobs/{job_id}
```

### Approve a job

```http
POST /api/v1/jobs/{job_id}/approve
```

### Reject a job

```http
POST /api/v1/jobs/{job_id}/reject
```

### Retry a failed stage

```http
POST /api/v1/jobs/{job_id}/retry
```

### Create a manual topic

```http
POST /api/v1/topics
```

### Render from an existing script package

```http
POST /api/v1/render
```

This endpoint is useful during development because rendering can be tested independently of research and script generation.

---

## 22. Quality Validation

Every final video must pass automatic checks.

### Technical checks

- File exists
- MP4 container is valid
- H.264 video exists
- AAC audio exists
- Resolution is 1080×1920
- Frame rate is valid
- Duration is within configured range
- Audio is present
- No long silence
- No black first or last frame
- No corrupted frames
- File size is within limits

### Content checks

- Title is visible
- Labels fit
- No subtitle exceeds safe bounds
- Mascot exists in every required scene
- Mascot points to the correct side
- Left and right images are not swapped
- Every factual claim was verified
- No unsupported URLs appear
- No watermark from another creator
- No duplicate topic
- No repeated script beyond the similarity threshold

### Preview outputs

Generate:

- Final MP4
- Poster frame
- Contact sheet
- Low-resolution preview
- Caption text
- Hashtag text
- Sources JSON
- Cost JSON
- Debug timeline JSON

---

## 23. Cost Tracking

Every external API call should log estimated cost.

Example:

```python
class CostRecord(BaseModel):
    job_id: UUID
    provider: str
    operation: str
    units: float
    unit_type: str
    estimated_cost_usd: float
```

Track:

- LLM input tokens
- LLM output tokens
- Search calls
- TTS characters
- Image generations
- Storage
- Publishing service usage

Produce per-video totals:

```json
{
  "research": 0.012,
  "script": 0.008,
  "verification": 0.006,
  "tts": 0.11,
  "images": 0.084,
  "storage": 0.001,
  "total": 0.221
}
```

---

## 26. Error Handling

Every pipeline stage must be idempotent.

If a job fails during TTS, re-running it should not repeat research and image generation unnecessarily.

Use stage checkpoints:

```text
TOPIC_SELECTED
RESEARCH_COMPLETE
SCRIPT_COMPLETE
VERIFICATION_COMPLETE
ASSETS_COMPLETE
TTS_COMPLETE
TIMING_COMPLETE
RENDER_COMPLETE
QUALITY_COMPLETE
UPLOADED
```

Store output paths and hashes after every stage.

### Retry policy

Retry automatically for:

- Rate limits
- Temporary network errors
- 5xx API errors
- Timeouts
- Temporary storage failures

Do not retry automatically for:

- Invalid prompt output after multiple repair attempts
- Unsupported factual claim
- Missing required source
- Invalid channel configuration
- Missing mascot asset
- Copyright or policy rejection

---

## 27. Logging and Observability

Use structured logs.

Every log line should include:

- Job ID
- Channel ID
- Topic ID
- Stage
- Provider
- Duration
- Retry count
- Cost where applicable

Expose:

```http
GET /health
GET /ready
GET /metrics
```

Optional:

- Prometheus
- Grafana
- Sentry

Create a debug bundle when a job fails:

```text
debug/
├── job.json
├── research.json
├── script.json
├── verification.json
├── scenes.json
├── ffmpeg-command.txt
├── logs.txt
└── generated-assets/
```
