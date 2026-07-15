# Mini-PC Telegram and Buffer Automation Design

Date: 2026-07-15

## Objective

Run the complete Mascot Poster application stack inside VM 100 on the home-server mini PC. Generate two candidate videos each day, require explicit approval from the owner in Telegram, and publish an approved video to TikTok through Buffer. No video may be uploaded to public storage or sent to a publishing provider before approval.

All application components run on the mini PC. The stack makes outbound calls to the configured text, image, search, TTS, Telegram, Cloudflare R2, Buffer, and TikTok services. The Mascot Poster API and n8n do not require public inbound access.

## Selected Approach

Use the existing private n8n installation as the scheduler and workflow orchestrator. Add a durable Mascot Poster API, one generation worker, a private PostgreSQL database, and a small Telegram bot that uses outbound long polling. After approval, stage the final MP4 temporarily in Cloudflare R2 and ask Buffer to publish it to the connected TikTok channel.

Do not pursue a private TikTok Direct Post application. TikTok's published intended-use rules make an internal account-management uploader a poor candidate for Direct Post approval. Buffer supplies the approved publishing bridge, while manual posting remains the emergency fallback.

OpenClaw is not part of this design. The required Telegram commands are deterministic and do not justify a general-purpose agent with command-execution privileges.

## Components

### n8n

n8n owns schedules, calls internal Mascot Poster endpoints, monitors deadlines, reacts to internal Telegram events, requests publishing, and sends operational alerts. Workflows pass job identifiers and small JSON payloads. They do not carry MP4 data in n8n execution storage.

n8n remains on its existing pinned deployment and private network path. The Mascot stack joins a narrowly scoped Docker network that permits the required service-to-service calls without publishing the Mascot API to the dorm LAN.

### Mascot Poster API

The FastAPI service provides authenticated internal endpoints for:

- creating scheduled and manual jobs;
- reading job state and artifacts;
- approving, rejecting, and requesting targeted regeneration;
- publishing an approved job;
- querying Buffer publication state;
- performing retention cleanup;
- health and readiness checks.

The API stores durable state in PostgreSQL. The current process-local job dictionary is removed from production behavior.

### Generation worker

One worker claims queued jobs from PostgreSQL and runs the existing research, script, image, TTS, rendering, and quality stages. Concurrency is fixed at one because VM 100 has 10 GiB RAM and also hosts other services. Stage checkpoints make retries resume from completed work instead of repeating paid provider calls unnecessarily.

The worker writes artifacts to a persistent host directory mounted into the API, worker, and Telegram bot containers. Each job has a separate directory containing the final MP4, preview, poster, caption, cost report, source report, quality report, and debug artifacts.

### PostgreSQL

A dedicated PostgreSQL container stores jobs, state transitions, approval records, artifact metadata, provider publication identifiers, and cleanup deadlines. PostgreSQL also acts as the simple queue through row claiming and locking; Redis and a second queueing system are unnecessary for a single worker.

### Telegram bot

The Telegram bot uses the Bot API's outbound long-polling method. This avoids exposing an n8n or application webhook to the public Internet.

Only configured Telegram user and chat identifiers are accepted. Unknown chats receive no operational information and cannot invoke actions. Callback identifiers are short, single-use references mapped to server-side records; they never contain secrets or trusted state.

For a completed job, Telegram sends a low-resolution preview or the final MP4 when it fits Telegram's limits, followed by the topic, caption, cost, target slot, and buttons for:

- Approve and schedule;
- Edit caption;
- Reject;
- Regenerate script;
- Regenerate images;
- Regenerate the entire video.

Operational commands are limited to:

- `/status` for today's slots and current jobs;
- `/queue` for queued and running jobs;
- `/cancel <job-id>` for a job that has not entered publishing.

There is no Telegram idea-generation command.

### Cloudflare R2

After approval, the application uploads the final MP4 to an R2 bucket using a high-entropy object name. The object is available through a direct public HTTPS URL because Buffer must fetch the media without authentication. The R2 bucket does not expose the mini PC or its local filesystem.

Objects receive a cleanup deadline 48 hours after Buffer confirms publication. A periodic cleanup workflow removes expired objects and records the outcome. Failed deletion is retried and alerted; it does not change the publication result.

### Buffer

The application uses a Buffer personal API key and the selected TikTok channel identifier. It creates a TikTok video post using the R2 URL, approved caption, selected thumbnail offset, and AI-generated-content disclosure.

The application stores the Buffer post identifier and polls Buffer for the final state. A successful API request is not treated as a successful TikTok publication until Buffer reports a sent/published result. Failures produce a Telegram alert and preserve the local video for manual posting.

## Daily Workflow

The initial timezone is `Europe/Bucharest`.

1. n8n creates generation jobs at 07:30 and 15:30.
2. The corresponding target publishing slots are 09:00 and 17:00.
3. The worker claims one job, runs the pipeline, and records stage checkpoints.
4. Automatic quality checks must pass before the job becomes `WAITING_FOR_APPROVAL`.
5. Telegram sends the preview and approval controls.
6. No approval leaves the job waiting. It does not upload to R2 or Buffer.
7. Approval records the Telegram user, chat, time, approved caption, video SHA-256, and a single-use action identifier.
8. Approval before the target time schedules the Buffer post for the target time.
9. Approval after the target time but within three hours requests immediate publishing.
10. A job still unapproved three hours after its target becomes `MISSED` and cannot publish without a new explicit approval action.
11. Buffer state is polled until success, terminal failure, or timeout.
12. Telegram reports the confirmed outcome and supplies a manual-post fallback when publishing fails.

The two daily slots are configuration values rather than hard-coded assumptions.

## State and Idempotency

The main states are:

`QUEUED`, `RUNNING`, `WAITING_FOR_APPROVAL`, `APPROVED`, `STAGING_MEDIA`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`, `REJECTED`, `MISSED`, `FAILED`, and `CANCELLED`.

State changes use database transactions. Approval requires the expected video hash and current `WAITING_FOR_APPROVAL` state. Only one transaction may move a job into publishing. Duplicate Telegram callbacks return the existing result without creating another Buffer post.

Because a network timeout can make Buffer submission ambiguous, the application records the submission attempt before sending it and reconciles recent Buffer posts before retrying. It does not blindly resubmit an ambiguous request.

Targeted regeneration invalidates the previous approval, creates a new artifact version and hash, and returns the job to `RUNNING`. A newly rendered version requires a new approval.

## Weekly Idea Prompt

The repository includes a reusable Markdown prompt intended for a weekly Codex 5.6 Sol Ultra session. It is a planning artifact, not executable application code.

The prompt:

- accepts a configurable candidate count, defaulting to 30;
- accepts the existing topic history and user blacklist;
- requests Romanian output;
- enforces two concrete, visually distinct physical objects;
- rejects abstract, label-dependent, diagram-dependent, interface-dependent, and subtly differentiated subjects;
- scores hook strength, visual clarity, factual depth, novelty, research difficulty, image-acquisition difficulty, and factual risk;
- performs a second-pass critique that removes weak candidates;
- returns a ranked Markdown table, a strongest-candidates shortlist, and a CSV-compatible fenced block;
- does not edit files, start jobs, call publishing services, or claim that an idea has been fact-checked.

The owner manually chooses and modifies ideas, then supplies the selected comparison to Mascot Poster through its manual-job path.

## Secrets and Access

No real secret is committed to Git. Runtime secrets live in an owner-only environment file outside the Compose project and include:

- OpenRouter and other generation-provider credentials;
- ElevenLabs credentials;
- Telegram bot token and allowed identifiers;
- PostgreSQL password;
- R2 endpoint, access key, secret key, bucket, and public base URL;
- Buffer API key and TikTok channel identifier;
- internal n8n-to-application authentication token.

The API rejects missing or invalid internal authentication. The API port is bound only where required for the private Docker network and optional loopback diagnostics. PostgreSQL is not published on a host port.

## Retention and Backups

- Published local job artifacts are retained for 30 days.
- Rejected, cancelled, missed, and failed artifacts are retained for 7 days.
- R2 media is removed 48 hours after confirmed publication.
- Cleanup is idempotent and reports failures without deleting database history.
- Compose files, non-secret configuration, schema migrations, workflows, and recovery instructions are reproducible in Git.
- The real environment file and database backup require a separately protected backup process and are never added to the repository.

Deployment is not considered complete until a PostgreSQL backup and isolated restore test are documented.

## Error Handling

Transient provider errors use bounded exponential retry. Invalid content, policy rejection, failed quality validation, missing assets, and exhausted paid-provider repair loops stop for human review rather than retrying indefinitely.

A failed scheduled job sends a Telegram alert containing the job identifier, failed stage, concise error, retry availability, and local artifact retention deadline. A worker restart returns abandoned running jobs to a recoverable state after a lease expires.

If R2 or Buffer is unavailable, the approved local MP4 remains available and the user can retry publishing or post manually. Generation failures cannot trigger publishing.

## Verification

Automated tests cover:

- job state transitions and illegal transitions;
- database queue claiming and expired worker leases;
- Telegram allowlisting, callbacks, duplicate presses, and caption edits;
- approval hash binding and invalidation after regeneration;
- scheduling before and after a target slot;
- missed-slot behavior;
- R2 staging and cleanup using mocked provider calls;
- Buffer request construction, reconciliation, polling, and failures;
- prevention of duplicate Buffer submissions;
- weekly prompt structure and required sections;
- Compose configuration validation.

Deployment verification proceeds in stages:

1. Start the database, API, worker, and bot without activating schedules.
2. Pass health, readiness, migration, and container-restart checks.
3. Generate one manual test video without publishing.
4. Verify Telegram approval, rejection, regeneration, and unauthorized-chat behavior.
5. Publish a test through Buffer to a safe TikTok visibility setting selected during account setup.
6. Confirm Buffer/TikTok status reconciliation and Telegram success reporting.
7. Verify R2 cleanup after an intentionally shortened test deadline.
8. Activate one daily slot, observe it end to end, then activate the second slot.
9. Complete and document database backup and isolated restore testing.

## Deployment and User Responsibilities

Implementation supplies the application code, migrations, tests, Compose definition, n8n workflow exports, example environment file, weekly idea prompt, deployment instructions, and recovery documentation.

The owner must perform external account and consent actions that cannot be automated safely:

- create the Telegram bot and provide its token plus allowed IDs;
- create or select an R2 bucket, public delivery hostname, and restricted credentials;
- create a Buffer account, connect the TikTok account through Buffer's OAuth flow, and provide a Buffer API key and channel identifier;
- confirm TikTok account publishing options and AI-content disclosure behavior;
- place provider credentials in the server-side secret file;
- approve the first safe test publication;
- decide when to activate the two production schedules.

No external credential, OAuth consent, public publication, or destructive server operation is performed without the owner's explicit participation.
