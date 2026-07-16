# AI Social Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a fact-grounded, playful-expert social description after the final narration is stable, show the exact publishable text in Telegram, and pass it unchanged to Buffer.

**Architecture:** A focused `SocialDescriptionService` uses the configured script LLM and returns a validated `SocialDescription`. A small JSON history service supplies recent descriptions and records bounded results. `VideoGenerationService` checkpoints this stage after `direction_tts`; the automation worker reads its final text with a legacy fallback.

**Tech Stack:** Python 3.12, Pydantic v2, existing structured LLM providers, JSON checkpoints/history, pytest, Docker Compose.

## Global Constraints

- Work directly on `main`, as explicitly requested by the user.
- Preserve all unrelated modified and untracked files in the working tree.
- Use TDD: every production behavior begins with a focused failing test.
- Romanian descriptions use 25–45 words, `X vs Y`, a concrete supported contrast, a final question, and playful-expert tone.
- Never copy `nu știam nici eu` or Nea Caisă persona wording.
- Publish three to five normalized hashtags with `pufaila` and `stiaica` first and exactly one `#` each.
- Telegram and Buffer must use the identical composed text.
- Existing published posts are never edited.
- A dedicated-description failure falls back to the legacy AI script caption rather than discarding a completed video.

---

### Task 1: Structured description model and writer

**Files:**
- Modify: `src/app/domain/models.py`
- Create: `src/app/services/social_description_service.py`
- Test: `tests/unit/test_social_description.py`

**Interfaces:**
- Consumes: `TopicSpec`, `ResearchPackage`, `ReferenceScriptPackage`, language string, recent description strings, and an object exposing `complete_structured(...)`.
- Produces: `SocialDescription(description: str, hashtags: list[str], fallback_used: bool = False)`, `SocialDescription.publishable_text`, and `SocialDescriptionService.generate(...) -> SocialDescription`.

- [ ] **Step 1: Write failing model and normalization tests**

Cover a valid Romanian description, rejection outside 25–45 words, missing comparison opening, missing final question, hashtag normalization from `#Pufăilă`, duplicate removal, required branded tags, unsupported punctuation removal, exact-one-`#` formatting, and a five-tag cap.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/test_social_description.py -q`

Expected: collection/import failure because `SocialDescription` and `SocialDescriptionService` do not exist.

- [ ] **Step 3: Implement the minimal structured model and deterministic formatter**

Add a Pydantic model that validates description structure, exposes normalized hashtag tokens, and composes:

```text
<description>

#pufaila #stiaica #category #left #right
```

Implement normalization using Unicode NFKD folding, ASCII alphanumerics only, ordered deduplication, forced brand tags, and a five-tag maximum.

- [ ] **Step 4: Add failing prompt/repair/fallback tests**

Use a recording fake LLM to assert the prompt contains the final narration, verified facts, recent descriptions, playful-expert rules, 25–45 words, fact-only constraint, and anti-copy language. Test one invalid structured response followed by a valid repair response. Test two failures producing a normalized fallback from the legacy script caption and hashtags with `fallback_used=True`.

- [ ] **Step 5: Run the new behavior tests and verify RED**

Run: `python -m pytest tests/unit/test_social_description.py -q`

Expected: formatter tests pass but writer tests fail because `generate` is incomplete.

- [ ] **Step 6: Implement prompt generation, one repair attempt, and fallback**

The service calls `complete_structured(..., SocialDescription, schema_name="social_description", temperature=0.45, max_tokens=700)`. It catches validation/provider errors, retries once with the error as a concise repair note, and then builds a fallback from `script.caption` and `script.hashtags`.

- [ ] **Step 7: Verify Task 1 GREEN**

Run: `python -m pytest tests/unit/test_social_description.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit Task 1**

Stage only the Task 1 files and commit `feat: add AI social description writer`.

---

### Task 2: Bounded persistent description history

**Files:**
- Create: `src/app/services/description_history.py`
- Modify: `src/app/config.py`
- Test: `tests/unit/test_description_history.py`

**Interfaces:**
- Produces: `DescriptionHistoryService(path: Path, max_entries: int = 50)`, `recent(limit: int = 10) -> list[str]`, and `add(topic_title: str, description: str) -> None`.
- Produces: cached `get_description_history_service()` from `settings.data_dir / "description_history.json"`.

- [ ] **Step 1: Write failing history tests**

Test missing-file startup, UTF-8 JSON persistence, duplicate suppression by exact topic/description pair, most-recent-ten order, malformed-file recovery, and retention of only the newest fifty entries.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/test_description_history.py -q`

Expected: import failure because the service does not exist.

- [ ] **Step 3: Implement atomic bounded history**

Store objects with `topic`, `description`, and UTC ISO `created_at`. Write through a sibling temporary file and `Path.replace` so interruption cannot leave partial JSON. Do not store captions containing secrets or any other job fields.

- [ ] **Step 4: Expose the cached configured service**

Add `get_description_history_service()` beside `get_topic_history_service()` in `config.py`.

- [ ] **Step 5: Verify Task 2 GREEN**

Run: `python -m pytest tests/unit/test_description_history.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

Stage only the Task 2 files and commit `feat: persist recent social descriptions`.

---

### Task 3: Pipeline stage and regeneration semantics

**Files:**
- Modify: `src/app/services/video_generation_service.py`
- Modify: `src/app/services/reference_generation_factory.py`
- Modify: `src/app/automation/checkpoints.py`
- Modify: `tests/unit/test_reference_pipeline.py`
- Modify: `tests/unit/test_reference_generation.py`
- Modify: `tests/unit/test_automation_worker.py`

**Interfaces:**
- `VideoGenerationService.__init__` gains `social_description_writer` and `description_history` dependencies.
- `social_description.json` stores `{ "description": <SocialDescription>, "publishable_text": <str> }`.
- Script/full regeneration invalidates `social_description`; image regeneration preserves it.

- [ ] **Step 1: Add failing pipeline placement and checkpoint tests**

Extend the pipeline fakes so the description writer records the exact final script it receives. Force one duration repair and assert the writer receives the repaired script, runs once after `direction_tts`, saves `social_description`, records history once, and reuses the checkpoint on resume.

- [ ] **Step 2: Run the focused pipeline tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_pipeline.py -k "social_description" -q`

Expected: failures because the new constructor dependencies and stage do not exist.

- [ ] **Step 3: Implement the pipeline stage**

After the `direction_tts` block, load or generate `SocialDescription`, compose the publishable text, save the checkpoint, and append history only when the checkpoint is newly created. The render result and video content remain unchanged.

- [ ] **Step 4: Add failing factory and invalidation tests**

Assert the factory injects `SocialDescriptionService(script_llm)` and configured history. Assert script/full invalidation sets include `social_description`; image invalidation does not.

- [ ] **Step 5: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_automation_worker.py -k "social_description or checkpoints" -q`

Expected: invalidation/factory assertions fail before implementation.

- [ ] **Step 6: Wire the factory and checkpoint invalidation**

Create the service from the existing script LLM and pass `get_description_history_service()`. Add `social_description` to `RegenerationKind.SCRIPT` and `RegenerationKind.FULL`, leaving `IMAGES` unchanged.

- [ ] **Step 7: Verify Task 3 GREEN**

Run: `python -m pytest tests/unit/test_reference_pipeline.py tests/unit/test_reference_generation.py tests/unit/test_automation_worker.py -q`

Expected: all selected suites pass.

- [ ] **Step 8: Commit Task 3**

Stage only Task 3 hunks—these files contain unrelated user work—and commit `feat: checkpoint final social descriptions`.

---

### Task 4: Telegram/Buffer source of truth and legacy fallback

**Files:**
- Modify: `src/app/automation/worker.py`
- Modify: `tests/unit/test_automation_worker.py`
- Modify: `tests/unit/test_telegram_approval.py`
- Modify: `tests/unit/test_publishing.py`

**Interfaces:**
- `GenerationWorker._read_metadata(...)` prefers `_pipeline/social_description.json["publishable_text"]`.
- Jobs without the new checkpoint retain the current script-caption fallback.
- Telegram displays `job.caption`; `PublicationService` sends the identical `job.caption` to Buffer.

- [ ] **Step 1: Write failing worker source-of-truth tests**

Test that a social-description checkpoint overrides differing legacy caption fields byte-for-byte, and that an old job without the checkpoint still composes its legacy caption safely with normalized exactly-one-`#` hashtags.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/unit/test_automation_worker.py -k "social_description or legacy_caption" -q`

Expected: the new checkpoint test fails because the worker ignores it.

- [ ] **Step 3: Implement checkpoint preference and safe legacy formatting**

Read `publishable_text` only when it is a non-empty string. Otherwise use the existing legacy fields while preventing bare hashtag words and double `##` prefixes.

- [ ] **Step 4: Add exact Telegram-to-Buffer contract assertions**

Create a caption containing Romanian diacritics, emoji, newline separation, and hashtags. Assert Telegram's review caption contains it unchanged and the fake Buffer client receives the same string as `text` after approval.

- [ ] **Step 5: Run contract tests and verify GREEN**

Run: `python -m pytest tests/unit/test_automation_worker.py tests/unit/test_telegram_approval.py tests/unit/test_publishing.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

Stage only Task 4 hunks and commit `feat: publish approved AI descriptions`.

---

### Task 5: Full verification, deployment, and controlled acceptance

**Files:**
- Modify: `docs/mini-pc-deployment.md`
- Modify in home-server repository: `CURRENT_SETUP.md`, `TODO.md`, `CHANGELOG.md`

**Interfaces:**
- Deployment continues to require both `MASCOT_ENV_FILE=/home/alexandru/secrets/mascot-poster.env` and `docker compose --env-file /home/alexandru/secrets/mascot-poster.env`.

- [ ] **Step 1: Run repository verification**

Run `python -m pytest -q` and `git diff --check`. Also verify the exact staged snapshot so unrelated working-tree changes cannot hide missing dependencies.

Expected: full suite passes with no failures and staged diff check is clean.

- [ ] **Step 2: Document operation and rollback**

Document the new checkpoint, persistent history file, legacy fallback, regeneration invalidation, and that already published posts are untouched.

- [ ] **Step 3: Commit and push `main`**

Commit only the documentation hunk, verify `main`, then push to `origin/main`.

- [ ] **Step 4: Deploy without exposing secrets**

On VM 100, pull fast-forward only, build the worker image, and recreate the worker with both required external-env mechanisms. Do not print environment values.

- [ ] **Step 5: Verify production wiring without creating a post**

Inside the worker, instantiate the factory, confirm the new service/history dependencies exist, run a deterministic formatter example, and confirm all Mascot containers are healthy.

- [ ] **Step 6: Create one fresh review candidate**

Create or regenerate a non-published job so it runs the new description stage. Wait for Telegram and verify the description format, branded hashtags, job hash, and `WAITING_FOR_APPROVAL` state. Do not approve it automatically and do not edit the already published fridge/freezer post.

- [ ] **Step 7: Update infrastructure source-of-truth docs**

Record the deployed revision and verified behavior in `CURRENT_SETUP.md`, remove only completed acceptance items from `TODO.md`, add a dated `CHANGELOG.md` entry, and commit only those hunks in the home-server repository.

- [ ] **Step 8: Final verification**

Recheck deployed Git revision, clean VM checkout, worker health, pending Telegram candidate state, absence of Buffer/R2 identifiers on the unapproved candidate, and preservation of unrelated local changes.
