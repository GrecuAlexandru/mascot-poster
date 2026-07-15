# Mini-PC Telegram and Buffer Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Mascot Poster as a durable mini-PC service that generates two daily videos, requires owner approval in Telegram, and publishes approved videos through temporary R2 storage and Buffer.

**Architecture:** A FastAPI service and one database-backed worker share PostgreSQL and a persistent output volume. A long-polling Telegram bot records single-use approvals without public inbound webhooks; the API stages approved media in R2 and creates/reconciles Buffer posts. The existing private n8n instance only schedules and monitors internal HTTP operations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, psycopg 3, PostgreSQL 17, httpx, boto3, FFmpeg, Docker Compose, n8n 2.26.8, Telegram Bot API, Buffer GraphQL API, Cloudflare R2.

## Global Constraints

- All application containers and persistent application data run in VM 100 on the mini PC.
- The Mascot API, PostgreSQL, and n8n require no public inbound route.
- Worker concurrency is exactly one.
- Nothing uploads to R2 or Buffer before a hash-bound Telegram approval.
- Only configured Telegram user and chat IDs can read status or mutate jobs.
- No real credentials, tokens, private keys, or `.env` files enter Git.
- n8n passes identifiers and JSON metadata, never MP4 binaries.
- Published artifacts remain local for 30 days; other terminal artifacts remain for 7 days.
- R2 objects expire 48 hours after confirmed publication.
- The two initial generation times are 07:30 and 15:30 Europe/Bucharest; target slots are 09:00 and 17:00.
- An unapproved job becomes `MISSED` three hours after its target and never publishes automatically.
- The existing working-tree changes are user-owned and must not be included in feature commits accidentally.

---

## File Structure

- `src/app/automation/models.py`: automation enums and Pydantic API records.
- `src/app/automation/database.py`: SQLAlchemy engine, schema, sessions, and PostgreSQL queue locking.
- `src/app/automation/job_service.py`: state transitions, approval hash binding, leases, and retention.
- `src/app/automation/generation_runner.py`: adapter from durable jobs to `VideoGenerationService`.
- `src/app/automation/worker.py`: single-concurrency worker process.
- `src/app/automation/telegram_bot.py`: Bot API long polling, allowlist, previews, and callbacks.
- `src/app/automation/r2_storage.py`: R2 upload/delete adapter.
- `src/app/automation/buffer_client.py`: Buffer GraphQL submission and reconciliation.
- `src/app/automation/publishing.py`: approved-job staging and publication orchestration.
- `src/app/api/routes_automation.py`: authenticated internal automation routes.
- `src/app/prompts/weekly_content_ideas.md`: manual weekly Codex prompt.
- `tests/unit/test_automation_*.py`: focused unit tests for every boundary.
- `n8n/workflows/*.json`: importable schedule, monitor, and cleanup workflows.
- `docker-compose.yml`, `Dockerfile`, `.env.example`: reproducible mini-PC stack.
- `docs/DEPLOY_MINI_PC.md`: deployment, external-account actions, verification, backup, and rollback.

---

### Task 1: Weekly Manual Idea Prompt

**Files:**
- Create: `src/app/prompts/weekly_content_ideas.md`
- Create: `tests/unit/test_weekly_idea_prompt.py`

**Interfaces:**
- Consumes: pasted topic history, blacklist, niche, and candidate count.
- Produces: a ranked Romanian Markdown table, shortlist, and CSV block; no application side effects.

- [ ] **Step 1: Write the failing structure test**

```python
from pathlib import Path


def test_weekly_prompt_has_manual_inputs_scoring_and_csv() -> None:
    text = (Path(__file__).resolve().parents[2] / "src/app/prompts/weekly_content_ideas.md").read_text("utf-8")
    for marker in (
        "{candidate_count}", "{topic_history}", "{blacklist}",
        "visual_clarity", "image_acquisition_difficulty", "factual_risk",
        "Second-pass critique", "```csv", "Do not edit files",
    ):
        assert marker in text
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

Run: `python -m pytest tests/unit/test_weekly_idea_prompt.py -v`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create the complete reusable prompt**

Write a Markdown prompt containing role, pasted inputs, rigid two-object visual rules, explicit rejection rules, scoring definitions, a second-pass removal procedure, ranked Romanian output, a top-ten shortlist, and a CSV block. State that candidates are unverified proposals and the model must not edit files or trigger jobs.

- [ ] **Step 4: Run the prompt test**

Run: `python -m pytest tests/unit/test_weekly_idea_prompt.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the prompt**

```powershell
git add src/app/prompts/weekly_content_ideas.md tests/unit/test_weekly_idea_prompt.py
git commit -m "docs: add weekly content idea prompt"
```

### Task 2: Durable Job Model and State Machine

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/app/config.py`
- Create: `src/app/automation/__init__.py`
- Create: `src/app/automation/models.py`
- Create: `src/app/automation/database.py`
- Create: `src/app/automation/job_service.py`
- Create: `tests/unit/test_automation_jobs.py`

**Interfaces:**
- Produces: `JobState`, `RegenerationKind`, `AutomationJob`, `JobService.create_job()`, `claim_next()`, `complete_generation()`, `approve()`, `reject()`, `request_regeneration()`, `mark_missed()`, and `cancel()`.
- Consumes later: worker, bot, API, and publisher use these exact service methods.

- [ ] **Step 1: Add failing transition and duplicate-approval tests**

```python
def test_approval_binds_hash_and_is_single_use(job_service, ready_video):
    job = job_service.create_job(target_at=utc(2026, 7, 15, 9))
    job_service.complete_generation(job.id, ready_video, "caption")
    approved = job_service.approve(job.id, "sha256", telegram_user_id=7, telegram_chat_id=9)
    assert approved.state is JobState.APPROVED
    assert job_service.approve(job.id, "sha256", 7, 9).approval_id == approved.approval_id


def test_regeneration_invalidates_approval(job_service, ready_video):
    job = ready_job(job_service, ready_video)
    job_service.approve(job.id, job.video_sha256, 7, 9)
    regenerated = job_service.request_regeneration(job.id, RegenerationKind.IMAGES)
    assert regenerated.state is JobState.QUEUED
    assert regenerated.approved_video_sha256 is None
```

- [ ] **Step 2: Run the tests and confirm import failures**

Run: `python -m pytest tests/unit/test_automation_jobs.py -v`

Expected: FAIL because `app.automation` does not exist.

- [ ] **Step 3: Add database dependencies and settings**

Add `sqlalchemy>=2.0`, `psycopg[binary]>=3.2`, and `boto3>=1.35`. Add typed settings for `DATABASE_URL`, `AUTOMATION_OUTPUT_DIR`, `INTERNAL_API_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `TELEGRAM_ALLOWED_CHAT_ID`, R2 values, Buffer values, slots, grace period, and retention values.

- [ ] **Step 4: Implement job records and transitions**

Use a SQLAlchemy `AutomationJobRow` with UUID string primary key, optimistic `version`, state, request JSON, target time, lease fields, artifact fields, hashes, approval audit fields, publication fields, error, and cleanup deadlines. Validate state changes through an explicit allowed-transition map; never assign arbitrary states from API input.

- [ ] **Step 5: Implement atomic queue claiming**

For PostgreSQL, select the oldest eligible job using `with_for_update(skip_locked=True)`, set `RUNNING`, lease owner, and lease expiry in the same transaction. Tests use SQLite and one session while production uses PostgreSQL.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/unit/test_automation_jobs.py -v`

Expected: PASS for legal transitions, illegal transitions, duplicate callbacks, leases, hash binding, regeneration, cancel, and missed jobs.

- [ ] **Step 7: Commit durable jobs**

```powershell
git add pyproject.toml src/app/config.py src/app/automation tests/unit/test_automation_jobs.py
git commit -m "feat: add durable automation jobs"
```

### Task 3: Real Worker and Authenticated API

**Files:**
- Create: `src/app/automation/generation_runner.py`
- Create: `src/app/automation/worker.py`
- Create: `src/app/api/routes_automation.py`
- Modify: `src/app/main.py`
- Modify: `src/app/api/routes_jobs.py`
- Create: `tests/unit/test_automation_api.py`
- Create: `tests/unit/test_automation_worker.py`

**Interfaces:**
- Consumes: Task 2 `JobService`; existing `build_reference_generation_service(Settings)` and `GenerationRequest`.
- Produces: `GenerationRunner.run(job)`, worker CLI, `/api/v1/automation/jobs`, `/status`, `/approve`, `/reject`, `/regenerate`, `/cancel`, `/publish`, `/cleanup`, `/health`, and `/ready`.

- [ ] **Step 1: Write failing API authentication and worker tests**

```python
def test_internal_routes_require_bearer_token(client):
    assert client.post("/api/v1/automation/jobs", json={}).status_code == 401


def test_worker_completes_job_with_real_result_paths(fake_generation_service, job_service):
    job = job_service.create_job(target_at=utc(2026, 7, 15, 9))
    run_once(job_service, fake_generation_service)
    saved = job_service.get(job.id)
    assert saved.state is JobState.WAITING_FOR_APPROVAL
    assert saved.video_sha256
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/unit/test_automation_api.py tests/unit/test_automation_worker.py -v`

Expected: FAIL because routes and runner are missing.

- [ ] **Step 3: Implement generation adapter**

Build `GenerationRequest(topic_override=job.topic_override, language=job.language, target_duration_seconds=job.target_duration_seconds, voice_id=job.voice_id)`, call the reference generation service with `job_id`, compute the final MP4 SHA-256, read the script checkpoint for caption/topic metadata, and call `complete_generation`.

- [ ] **Step 4: Implement single-worker loop**

Claim one job, extend its lease during progress callbacks, run it, persist failures with the failed stage, and use a bounded idle poll. On SIGTERM finish the current database write and exit without claiming another job.

- [ ] **Step 5: Add authenticated automation router**

Require `Authorization: Bearer <INTERNAL_API_TOKEN>` with `secrets.compare_digest`. Return sanitized JSON containing no local secret values. Deprecate old in-memory create/publish behavior by keeping it outside the new `/automation` namespace and documenting that n8n uses only the new endpoints.

- [ ] **Step 6: Run focused and existing pipeline tests**

Run: `python -m pytest tests/unit/test_automation_api.py tests/unit/test_automation_worker.py tests/unit/test_reference_pipeline.py -v`

Expected: PASS.

- [ ] **Step 7: Commit worker and API**

```powershell
git add src/app/automation/generation_runner.py src/app/automation/worker.py src/app/api/routes_automation.py src/app/main.py src/app/api/routes_jobs.py tests/unit/test_automation_api.py tests/unit/test_automation_worker.py
git commit -m "feat: run durable video generation jobs"
```

### Task 4: Private Telegram Approval Bot

**Files:**
- Create: `src/app/automation/telegram_bot.py`
- Create: `tests/unit/test_automation_telegram.py`

**Interfaces:**
- Consumes: `JobService` states and methods from Task 2.
- Produces: `TelegramBot.poll_once()`, allowlisted commands, preview delivery, caption-edit conversation, and single-use callbacks.

- [ ] **Step 1: Write failing allowlist and callback tests**

```python
async def test_unknown_user_is_ignored(bot, telegram, ready_job):
    await bot.handle_update(message_update(user_id=999, chat_id=999, text="/status"))
    telegram.assert_no_messages()


async def test_approve_callback_records_exact_hash(bot, service, ready_job):
    await bot.handle_update(callback_update(7, 9, f"approve:{ready_job.action_token}"))
    assert service.get(ready_job.id).approved_video_sha256 == ready_job.video_sha256
```

- [ ] **Step 2: Verify test failures**

Run: `python -m pytest tests/unit/test_automation_telegram.py -v`

Expected: FAIL because the bot is missing.

- [ ] **Step 3: Implement long polling and allowlisting**

Call `getUpdates` with a persisted offset, reject every update whose user or chat differs from settings, and support `/status`, `/queue`, and `/cancel <job-id>`. Use `httpx.AsyncClient` and bounded retries.

- [ ] **Step 4: Implement preview and actions**

Send MP4 when within Telegram's configured limit, otherwise send the poster plus a size warning. Store opaque action tokens in PostgreSQL and render buttons for approve, edit caption, reject, and the three regeneration modes. Answer each callback query immediately, then update/edit the original message.

- [ ] **Step 5: Implement caption editing**

An `edit` callback places only that user/chat into a pending edit for one job. The next text message replaces the caption after length validation and requires a fresh Approve press.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/unit/test_automation_telegram.py -v`

Expected: PASS for allowlisting, status, cancellation, preview fallback, caption edits, duplicate callbacks, and regeneration.

- [ ] **Step 7: Commit the bot**

```powershell
git add src/app/automation/telegram_bot.py tests/unit/test_automation_telegram.py
git commit -m "feat: add private Telegram approval bot"
```

### Task 5: R2 and Buffer Publishing

**Files:**
- Create: `src/app/automation/r2_storage.py`
- Create: `src/app/automation/buffer_client.py`
- Create: `src/app/automation/publishing.py`
- Replace: `src/app/services/publishing_service.py`
- Create: `tests/unit/test_automation_publishing.py`

**Interfaces:**
- Consumes: approved jobs from `JobService`.
- Produces: `R2Storage.upload_video()`, `delete()`, `BufferClient.create_tiktok_post()`, `get_post()`, `find_matching_post()`, and `PublishingService.publish_approved_job()`.

- [ ] **Step 1: Write failing no-approval, request-shape, and ambiguity tests**

```python
async def test_publish_refuses_unapproved_job(publisher, ready_job):
    with pytest.raises(InvalidTransition):
        await publisher.publish_approved_job(ready_job.id)


async def test_buffer_payload_includes_ai_disclosure(buffer, http):
    await buffer.create_tiktok_post("channel", "caption", "https://cdn/video.mp4", due_at=None)
    assert "isAiGenerated" in http.last_graphql_query


async def test_timeout_reconciles_before_resubmit(publisher, buffer, approved_job):
    buffer.create.side_effect = httpx.TimeoutException("ambiguous")
    buffer.find_matching.return_value = BufferPost(id="existing", status="buffer")
    result = await publisher.publish_approved_job(approved_job.id)
    assert result.buffer_post_id == "existing"
    assert buffer.create.call_count == 1
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/unit/test_automation_publishing.py -v`

Expected: FAIL because adapters are missing.

- [ ] **Step 3: Implement R2 adapter**

Use an S3-compatible boto3 client, a `videos/<job-id>/<sha256-prefix>-<random>.mp4` key, `video/mp4` content type, and public URL construction from `R2_PUBLIC_BASE_URL`. Never log credentials or signed headers.

- [ ] **Step 4: Implement Buffer GraphQL client**

Create automatic TikTok posts with video URL, caption, due time, thumbnail offset, and `isAiGenerated: true`. Parse GraphQL mutation errors even on HTTP 200. Provide lookup/reconciliation queries by channel, creation window, caption, and media URL.

- [ ] **Step 5: Implement publish orchestration**

Lock the approved job, record an attempt before I/O, upload to R2, submit or reconcile Buffer, save identifiers, poll terminal state, notify the bot, and schedule the 48-hour R2 cleanup. Preserve the local MP4 on every failure.

- [ ] **Step 6: Implement cleanup**

Delete expired R2 objects and local terminal artifacts only after their deadlines. Record failures and retry later; never delete database audit rows.

- [ ] **Step 7: Run publishing tests**

Run: `python -m pytest tests/unit/test_automation_publishing.py tests/unit/test_platform.py -v`

Expected: PASS with the old invalid TikTok direct-post expectations removed or replaced by Buffer expectations.

- [ ] **Step 8: Commit publishing**

```powershell
git add src/app/automation/r2_storage.py src/app/automation/buffer_client.py src/app/automation/publishing.py src/app/services/publishing_service.py tests/unit/test_automation_publishing.py tests/unit/test_platform.py
git commit -m "feat: publish approved videos through Buffer"
```

### Task 6: n8n Workflows and Production Compose

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Replace: `n8n/workflows/generate_video.json`
- Replace: `n8n/workflows/approval_flow.json`
- Replace: `n8n/workflows/publish_video.json`
- Replace: `n8n/workflows/analytics_collection.json`
- Modify: `n8n/README.md`
- Create: `tests/unit/test_deployment_config.py`

**Interfaces:**
- Consumes: authenticated API routes from Task 3 and publishing/cleanup from Task 5.
- Produces: mini-PC containers and importable inactive workflows.

- [ ] **Step 1: Write failing deployment assertions**

```python
def test_compose_does_not_publish_database_or_api(compose):
    assert "ports" not in compose["services"]["postgres"]
    assert "ports" not in compose["services"]["api"]
    assert compose["services"]["worker"]["command"] == ["python", "-m", "app.automation.worker"]
    assert compose["services"]["bot"]["command"] == ["python", "-m", "app.automation.telegram_bot"]


def test_workflows_are_inactive_and_use_internal_api(workflows):
    assert all(not workflow["active"] for workflow in workflows)
    assert all("TELEGRAM_CHAT_ID" not in json.dumps(workflow) for workflow in workflows)
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/unit/test_deployment_config.py -v`

Expected: FAIL against the development scaffold.

- [ ] **Step 3: Replace Compose with production-targeted services**

Define `api`, `worker`, `bot`, `postgres`, and `searxng`; use health checks, dependency conditions, one shared output volume, one Postgres volume, the external secret env file, no database/API host ports, read-only asset mounts where possible, and resource-aware restart policies. Join an external `n8n-mascot` network for private n8n-to-API access.

- [ ] **Step 4: Replace n8n skeleton workflows**

Create two Schedule Trigger workflows at 07:30 and 15:30, one monitor workflow that checks overdue jobs and publishes approved jobs, and one cleanup workflow. Every HTTP request includes the internal bearer credential configured in n8n. Keep all workflows inactive on import.

- [ ] **Step 5: Expand environment example and n8n instructions**

Document names only, never values. Explain the existing n8n container's external network attachment and how to create an n8n Header Auth credential instead of embedding the token in workflow JSON.

- [ ] **Step 6: Run deployment tests and Compose validation**

Run: `python -m pytest tests/unit/test_deployment_config.py -v`

Run: `docker compose --env-file .env.example config --quiet`

Expected: both commands succeed without revealing secrets.

- [ ] **Step 7: Commit deployment artifacts**

```powershell
git add Dockerfile docker-compose.yml .env.example n8n tests/unit/test_deployment_config.py
git commit -m "ops: add mini-pc automation stack"
```

### Task 7: Runbook, Full Verification, and Home-Server Documentation

**Files:**
- Create: `docs/DEPLOY_MINI_PC.md`
- Modify: `README.md`
- Modify in home-server repository after deployment state is known: `CURRENT_SETUP.md`, `TODO.md`, `CHANGELOG.md`, and `README.md` only as supported by verified facts.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a user-facing setup checklist, backup/restore commands, staged activation, and accurate home-server records.

- [ ] **Step 1: Write the deployment and recovery runbook**

Include prerequisites; directory ownership; secret-file creation; Telegram BotFather steps; `getUpdates` ID discovery; R2 bucket, restricted token, and public hostname; Buffer TikTok OAuth, API key, and channel ID; image build; schema initialization; health checks; manual generation; Telegram tests; safe Buffer test; schedule activation; log inspection; R2 cleanup; Postgres logical backup; isolated restore; update; stop; and rollback.

- [ ] **Step 2: Add explicit destructive-operation warnings**

For volume replacement, database restore, stack removal, and cleanup, state what changes, what data can be lost, how to back it up, and how to recover before showing any command.

- [ ] **Step 3: Run focused and full tests**

Run: `python -m pytest tests/unit/test_weekly_idea_prompt.py tests/unit/test_automation_jobs.py tests/unit/test_automation_api.py tests/unit/test_automation_worker.py tests/unit/test_automation_telegram.py tests/unit/test_automation_publishing.py tests/unit/test_deployment_config.py -v`

Run: `python -m pytest tests/ -v`

Expected: all tests pass; environment-dependent render tests may skip only for their existing documented fixture conditions.

- [ ] **Step 4: Build and smoke-test containers locally**

Run: `docker compose --env-file .env.example build`

Run: `docker compose --env-file .env.example config --quiet`

Expected: image build and configuration validation succeed. Do not activate schedules or call real providers with example credentials.

- [ ] **Step 5: Update documentation with verified scope only**

Before actual mini-PC deployment, describe files as ready for deployment and leave server installation in `TODO.md`. After deployment and verification, move only confirmed values to `CURRENT_SETUP.md` and add a dated changelog entry. Never describe OAuth, publication, backup, or restore as complete without observed evidence.

- [ ] **Step 6: Commit docs separately in each repository**

```powershell
git add README.md docs/DEPLOY_MINI_PC.md
git commit -m "docs: add mini-pc automation runbook"
```

In `homeserver`, stage only the exact documentation files changed for this feature and commit them separately after reviewing the existing dirty tree.
