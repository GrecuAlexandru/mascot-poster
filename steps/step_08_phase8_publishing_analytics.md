# Step 8 — Phase 8: Publishing and Analytics

> Goal of this step: publish approved videos across platforms, collect analytics
> snapshots, and run the whole stack through Docker Compose. Includes the
> Definition of Done for the initial production version.

Sections in this step:

- [Phase 8 milestone](#phase-8-publishing-and-analytics)
- [25. Publishing Strategy](#25-publishing-strategy)
- [30. Deployment on Linux Mini PC](#30-deployment-on-linux-mini-pc)
- [32. Definition of Done](#32-definition-of-done)

---

## Phase 8: Publishing and analytics

Add:

- TikTok posting integration
- YouTube Shorts
- Instagram Reels
- Analytics snapshots
- Performance reporting

Deliverable:

- Multi-platform publishing and tracking

---

## 25. Publishing Strategy

The publishing adapter should be separate from generation.

### Initial phase

Use a third-party publisher or upload as draft.

Advantages:

- Faster implementation
- Less API approval complexity
- Easier multi-platform posting

### Later phase

Use TikTok Content Posting API directly.

The application should expose a generic publication payload:

```python
class PublicationPayload(BaseModel):
    platform: str
    video_url: str
    caption: str
    scheduled_at: datetime | None
    privacy_level: str
    disclose_ai_generated: bool
    disclose_branded_content: bool
```

n8n handles platform-specific posting steps.

---

## 30. Deployment on Linux Mini PC

Use Docker Compose services:

```text
api
worker
postgres
redis
n8n
optional-minio
```

Example:

```yaml
services:
  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    restart: unless-stopped

  worker:
    build: .
    command: celery -A app.workers.celery_app worker --loglevel=INFO
    restart: unless-stopped

  postgres:
    image: postgres:17
    restart: unless-stopped

  redis:
    image: redis:7
    restart: unless-stopped

  n8n:
    image: n8nio/n8n:latest
    restart: unless-stopped
```

### Host requirements

Recommended:

- Ubuntu Server or Debian
- 8 GB RAM minimum
- 16 GB RAM preferred
- 256 GB SSD minimum
- Stable internet connection
- Automated backups
- Docker and Docker Compose
- FFmpeg installed in the application image

No dedicated GPU is required because AI generation is cloud-based.

---

## 32. Definition of Done

The initial production version is complete when:

- A topic can be selected automatically
- Sources are collected and stored
- A grounded script is generated
- Claims are verified
- Two images are generated or acquired
- Romanian or English TTS is generated
- Scene timing is produced
- Mascot poses are selected automatically
- A 1080×1920 MP4 is rendered
- Automatic checks pass
- Preview files are uploaded
- n8n sends an approval request
- Approval triggers publishing
- Publication status is recorded
- Per-video cost is recorded
- Failed jobs can be retried safely
- The full system runs through Docker Compose on Linux
