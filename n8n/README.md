# n8n workflows

The mini PC's existing n8n instance only schedules and orchestrates job IDs. MP4 files remain on the mascot stack's shared output volume and are never stored in n8n execution data.

## Private network connection

Create the shared Docker network once on VM 100:

```bash
docker network create n8n-mascot
```

Add the external network to the existing n8n Compose file:

```yaml
services:
  n8n:
    networks:
      - default
      - n8n-mascot

networks:
  n8n-mascot:
    external: true
```

After recreating n8n, it can reach the private API at `http://mascot-api:8000`. Neither service needs a host port for this connection.

## Authentication credential

In n8n, create a **Header Auth** credential named `Mascot Internal API`:

- Header name: `Authorization`
- Header value: `Bearer <AUTOMATION_INTERNAL_API_TOKEN>`

Use the same token stored in the mascot stack's external secrets file. The exported workflow JSON intentionally contains no token. After import, open every HTTP Request node and select the credential you created; the placeholder credential ID cannot be used as-is.

## Import and enable

Import all six JSON files from `n8n/workflows`. Keep them inactive until a manual test succeeds.

## Curated idea handoff

Use the two manual workflows before enabling scheduled generation:

1. Run `Mascot - Export idea history` and copy `copy_this_into_codex` from the final node.
2. Paste that history alongside `src/app/prompts/weekly_content_ideas.md` into Codex.
3. Copy the fenced JSON block from Codex's `n8n import` section.
4. Open `Mascot - Import idea batch`, edit the `ideas_json` value in `Paste Codex JSON here`, and paste the block.
5. Run the workflow and review `accepted_count`, `skipped_count`, and their details.

The queue is durable in PostgreSQL. The twice-daily workflow consumes the oldest accepted idea exactly once. When no idea is queued, it returns `NO_IDEA_AVAILABLE` and creates no generation job.

1. Import at least one harmless test idea through `Mascot - Import idea batch`.
2. Run `Mascot - Create twice-daily generation jobs` manually and confirm a `CREATED` response containing a `QUEUED` job is returned.
3. Let the worker finish and confirm the Telegram bot sends the MP4 with review buttons.
4. Approve a test video and run `Mascot - Publish newly approved videos` manually.
5. Confirm the post appears in Buffer, then run `Mascot - Reconcile Buffer delivery`.
6. Activate the create, publish, and reconciliation workflows. The history export, batch import, and daily audit workflows remain manual.

The create workflow runs at 07:30 and 15:30 in `Europe/Bucharest`, targeting 09:00 and 17:00. The publish workflow checks for approvals every two minutes. The reconciliation workflow checks Buffer every five minutes.

Telegram is intentionally not configured in n8n. The dedicated bot container uses outbound long polling, performs the strict approval checks against PostgreSQL, and never requires a public webhook.
