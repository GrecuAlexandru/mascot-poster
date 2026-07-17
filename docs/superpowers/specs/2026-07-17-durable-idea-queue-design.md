# Durable Idea Queue Design

## Objective

Provide a human-curated handoff between Codex weekly idea planning and the automated home-server video pipeline. The operator exports complete idea history from n8n, supplies that history to the reusable Codex prompt, imports Codex's structured output through an n8n input field, and lets the scheduled workflow consume queued ideas exactly once.

## Operator workflow

1. The operator manually executes `Mascot - Export idea history` in n8n.
2. The workflow calls the private mascot API and returns one copy-ready Markdown history block in its final node output.
3. The operator pastes that block alongside `src/app/prompts/weekly_content_ideas.md` into Codex.
4. Codex returns the normal editorial report plus one fenced JSON import block.
5. The operator opens `Mascot - Import idea batch`, pastes the JSON block into a single editable n8n field, and manually executes the workflow.
6. The workflow validates the JSON and sends it to the private mascot API.
7. The API reports which ideas were accepted and which were skipped, with a reason for every skipped row.
8. The twice-daily generation workflow requests the next queued idea. If one exists, the API creates a job and consumes the idea in the same database transaction.
9. If the queue is empty, no job is created. n8n receives a successful, explicit `NO_IDEA_AVAILABLE` result.

## Import contract

The prompt produces this exact structure:

```json
{
  "ideas": [
    {
      "idea_id": "IDEA-001",
      "title": "Gem vs dulceață",
      "left": "Gem",
      "right": "Dulceață",
      "angle": "Diferențele de textură, ingrediente și preparare."
    }
  ]
}
```

`idea_id` is the stable identifier from the Codex batch. `title`, `left`, and `right` are required non-empty strings. `angle` may be empty. Each side is limited to 200 characters, the title to 300 characters, the angle to 2,000 characters, and a batch to 100 ideas.

The API derives the generator override from `left` and `right` as `Left vs Right`. It does not attempt to parse the title. This removes the existing ambiguity around titles containing punctuation or explanatory text.

## Persistence model

Add an `automation_ideas` table alongside `automation_jobs` with:

- `id`: server-generated UUID primary key.
- `external_id`: nullable Codex batch identifier such as `IDEA-001`.
- `title`, `left_item`, `right_item`, and `angle`: imported editorial fields.
- `normalized_pair`: order-independent normalized key used for deduplication, protected by a unique database constraint.
- `state`: `QUEUED` or `CONSUMED`.
- `created_at` and `consumed_at`: audit timestamps.
- `automation_job_id`: nullable link to the job that consumed the idea.

Add nullable `idea_id` to `automation_jobs`. Existing rows remain valid and require no backfill.

Database schema creation continues through SQLAlchemy metadata. PostgreSQL deployment startup and SQLite tests create the new table and nullable column for new databases. Because `create_all` does not alter an existing PostgreSQL table, startup also performs an idempotent `ALTER TABLE automation_jobs ADD COLUMN IF NOT EXISTS idea_id VARCHAR(36)` before normal operation.

## Deduplication

Pair normalization is case-insensitive, diacritic-insensitive, punctuation-insensitive, whitespace-insensitive, and order-independent. `Gem vs Dulceață` and `dulceata vs gem` therefore have the same normalized key.

An imported idea is skipped when its normalized pair already appears in any of these sources:

- another row in the same import batch;
- any queued or consumed `automation_ideas` row;
- any automation job's `topic_override` that can be parsed as `Left vs Right`;
- any completed automation job's recorded `topic` that can be parsed as `Left vs Right`;
- any entry in the persistent `data/topic_history.json` service.

Malformed or unparseable historical titles remain visible in the export but do not create unreliable deduplication keys.

Imports are idempotent by normalized pair. Reimporting the same Codex output accepts zero duplicates and reports each duplicate explicitly.
The unique constraint is the final guard against concurrent imports. A constraint collision is converted to a `duplicate_pair` skipped result instead of surfacing as a server error.

## API design

All routes remain under `/api/v1/automation` and use the existing bearer-token dependency.

### Import ideas

`POST /api/v1/automation/ideas/import`

Consumes the JSON import contract and returns:

```json
{
  "accepted": [
    {
      "id": "server-uuid",
      "idea_id": "IDEA-001",
      "title": "Gem vs dulceață",
      "left": "Gem",
      "right": "Dulceață",
      "angle": "Diferențele de textură, ingrediente și preparare.",
      "state": "QUEUED"
    }
  ],
  "skipped": [
    {
      "idea_id": "IDEA-002",
      "title": "Dulceață vs gem",
      "reason": "duplicate_pair"
    }
  ]
}
```

Validation errors for the outer request return HTTP 422. Row-level duplicate decisions return HTTP 200 with `skipped` entries.

### Export history

`GET /api/v1/automation/ideas/history`

Returns structured `used`, `queued`, and `legacy` collections plus a `markdown` field. The Markdown is ready to paste into the `{topic_history}` input of the weekly prompt and clearly labels queued ideas so Codex avoids proposing them again.

History is sorted deterministically: consumed/used entries by their earliest known use time, queued entries by queue insertion time, and legacy-only entries in their stored order. The Markdown output deduplicates reversed and normalized pairs while retaining the earliest available display labels.

### Consume the next idea

Extend `POST /api/v1/automation/jobs` with `use_next_idea: bool = false`.

- An explicit `topic_override` and `use_next_idea=true` is rejected with HTTP 422.
- With `use_next_idea=false`, current behavior is unchanged.
- With `use_next_idea=true` and a queued idea, the API locks the oldest queued row, creates the automation job with `topic_override="Left vs Right"`, links both records, marks the idea consumed, and commits once.
- PostgreSQL uses `FOR UPDATE SKIP LOCKED` so concurrent schedulers cannot consume the same row.
- With `use_next_idea=true` and an empty queue, the API returns HTTP 200 with `{ "status": "NO_IDEA_AVAILABLE", "job": null }`.

The existing endpoint's response model becomes a small envelope capable of representing either a created job or an empty queue. n8n is the endpoint's only production client, and its workflow is updated in the same change.

## Service boundaries

`IdeaQueueService` owns validation-independent persistence operations, pair normalization, batch deduplication, history aggregation, Markdown export, and queue listing. `JobService` owns the transaction that consumes one queued idea and creates its job because both state changes must commit atomically.

The API layer owns Pydantic request and response schemas and maps the empty-queue result to the response envelope. n8n only accepts operator input, calls authenticated endpoints, and displays results; it is not the durable source of truth.

## n8n workflows

### Export workflow

Create `n8n/workflows/export_idea_history.json`:

- Manual Trigger.
- Authenticated HTTP Request to `/api/v1/automation/ideas/history`.
- Edit Fields node exposing the returned `markdown` as `copy_this_into_codex`.

The operator presses n8n's normal `Execute workflow` button and copies the final field.

### Import workflow

Create `n8n/workflows/import_idea_batch.json`:

- Manual Trigger.
- Edit Fields node containing one multiline string field named `ideas_json`. The imported workflow ships with a harmless empty `{"ideas":[]}` value.
- Code node that removes optional Markdown fences, parses JSON, and throws a clear error when parsing fails.
- Authenticated HTTP Request to `/api/v1/automation/ideas/import`.
- Edit Fields node exposing accepted and skipped counts and details.

The operator edits only the `ideas_json` field, pastes the fenced block or its JSON contents, and executes the workflow.

### Scheduled generation

Update `n8n/workflows/generate_video.json` so the target calculation emits `use_next_idea: true`. The workflow uses the response envelope to distinguish `CREATED` from `NO_IDEA_AVAILABLE`. Empty queue is a successful no-op, not an execution failure.

## Weekly prompt change

Keep the current editorial summary, ranked table, shortlist, and CSV export. Add a final `n8n import` section containing the exact fenced JSON contract. Only candidates present in the final ranked output may appear in the import block. Romanian strings retain correct diacritics.

The prompt tells the operator to copy the JSON block into the n8n `ideas_json` field and not to include invented research conclusions.

## Failure handling

- Invalid batch JSON fails in n8n before an API call.
- Invalid request structure returns HTTP 422 and creates no ideas.
- Duplicate rows are skipped without rolling back valid rows in the same batch.
- Database errors roll back the entire API transaction.
- Concurrent scheduled calls cannot consume the same idea.
- Empty queues create no job and do not invoke automatic topic generation.
- An idea is considered used when assigned to a job, even if generation later fails or the video is rejected. This prevents accidental repetition; requeueing is outside this feature's scope.

## Security

The new endpoints use the existing internal bearer token. No mascot API or database port is exposed to the VM host or public network. The n8n workflow exports contain placeholder credential references and no secrets. The history export contains topic metadata only.

## Testing

Unit and API tests cover:

- normalization and reversed-pair equality;
- batch import and row-level duplicate reporting;
- duplicate detection against queued, consumed, job, and legacy history sources;
- deterministic Markdown history export;
- authentication on both new routes;
- atomic oldest-first queue consumption;
- no duplicate consumption across sequential claims;
- empty-queue response without a created job;
- rejection of conflicting explicit override and queue consumption;
- new database schema fields;
- n8n workflow structure, private URLs, credential placeholders, and queue-first request body;
- weekly prompt inclusion of the exact JSON import contract.

The complete unit test suite remains the final regression gate.

## Out of scope

- A new Desktop or web UI.
- Editing, deleting, prioritizing, or requeueing imported ideas.
- Automatically invoking Codex from n8n.
- Public webhooks or public API exposure.
- Migrating historical free-form titles that cannot be reliably parsed as comparisons.
