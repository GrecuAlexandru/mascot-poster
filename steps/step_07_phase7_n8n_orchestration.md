# Step 7 — Phase 7: n8n Orchestration

> Goal of this step: wire Python and n8n together for end-to-end automatic
> generation with a human approval step. n8n schedules jobs, receives the
> completion webhook, sends approval previews, and notifies on failures.

Sections in this step:

- [Phase 7 milestone](#phase-7-n8n-orchestration)
- [24. n8n Workflow Design](#24-n8n-workflow-design)

---

## Phase 7: n8n orchestration

Add:

- Scheduled trigger
- Job creation
- Completion webhook
- Telegram or Discord approval
- Publish workflow
- Failure notifications

Deliverable:

- End-to-end automatic generation with human approval

---

## 24. n8n Workflow Design

## Workflow 1: Scheduled generation

Trigger:

- Cron
- Example: every day at 09:00 and 17:00

Steps:

1. Select channel
2. Call `POST /api/v1/jobs`
3. Store job ID
4. Poll job status or wait for callback
5. On success, continue to approval
6. On failure, send alert

---

## Workflow 2: Python completion webhook

Python calls n8n when the job is ready.

Payload:

```json
{
  "job_id": "uuid",
  "status": "WAITING_FOR_APPROVAL",
  "preview_url": "https://...",
  "video_url": "https://...",
  "caption": "...",
  "estimated_cost_usd": 0.22
}
```

n8n sends:

- Telegram message
- Discord message
- Email
- Slack message

Include:

- Preview link
- Caption
- Topic
- Cost
- Approve button
- Reject button
- Regenerate button

---

## Workflow 3: Approval

Approve button:

```http
POST /api/v1/jobs/{job_id}/approve
```

Then n8n:

1. Publishes through TikTok API or publishing service
2. Publishes to YouTube Shorts
3. Publishes to Instagram Reels
4. Records publication IDs
5. Sends success notification

Reject button:

```http
POST /api/v1/jobs/{job_id}/reject
```

Optional rejection reasons:

- Bad voice
- Wrong facts
- Poor images
- Repetitive topic
- Layout issue
- Other

Regenerate options:

- Script only
- Voice only
- Images only
- Full video
- Caption only

---

## Workflow 4: Analytics collection

> Note: this workflow is implemented alongside Step 8 (publishing & analytics).

Run periodically.

Collect:

- Views
- Likes
- Comments
- Shares
- Saves if available
- Average watch time if available
- Completion rate if available
- Follower increase
- Clicks
- Revenue if available

Store snapshots in PostgreSQL.

Use performance data later to influence topic selection.
