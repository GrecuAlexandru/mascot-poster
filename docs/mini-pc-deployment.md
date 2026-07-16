# Mini-PC deployment runbook

This stack runs entirely inside VM 100. n8n schedules work, PostgreSQL stores the audit state, the worker runs the existing mascot-poster generator, Telegram handles strict review, and Buffer publishes approved videos to TikTok. Cloudflare R2 is used only as temporary public media staging because Buffer requires a stable direct HTTPS URL.

No application or database port is published to the VM host. Telegram uses outbound long polling. The only public object is the unique R2 MP4 URL created after approval.

## 1. Accounts and credentials

### Telegram

1. Open `@BotFather`, run `/newbot`, and save the bot token in the password manager.
2. Open a private chat with the new bot and send `/start`.
3. Obtain the numeric user and chat IDs. In a shell, read the token without putting it in command history:

   ```bash
   read -rsp "Bot token: " TG_TOKEN
   echo
   curl --silent "https://api.telegram.org/bot${TG_TOKEN}/getUpdates"
   unset TG_TOKEN
   ```

4. For a private one-to-one chat, use your numeric user ID for `AUTOMATION_TELEGRAM_ALLOWED_USER_ID` and the returned chat ID for `AUTOMATION_TELEGRAM_REVIEW_CHAT_ID`.

The bot ignores every other user and chat. Do not add it to a group unless the allowlist is deliberately changed.

### Buffer and TikTok

1. Connect the target TikTok account as a Buffer channel and choose automatic publishing. Auto-published posts can use original audio; TikTok-only music, trending sounds, stickers, and in-app effects require notification publishing and are outside this automatic workflow.
2. In Buffer, open **Settings → API**, create a personal API key, and save it in the password manager.
3. Use Buffer's API Explorer to run **Get Organizations**, then **Get Channels**. Copy the channel whose `service` is TikTok into `AUTOMATION_BUFFER_TIKTOK_CHANNEL_ID`.
4. Before enabling n8n, manually publish one harmless test video through Buffer to confirm the TikTok connection and automatic-publishing permission work for the account and region.

This design does not require a TikTok developer application or Direct Post API audit. Buffer is the publishing integration. The remaining approval risk is the ordinary Buffer-to-TikTok channel authorization, not approval of a custom private TikTok uploader.

### Cloudflare R2

1. Create a dedicated bucket such as `mascot-buffer-media`.
2. Attach a custom public domain such as `media.example.com`. Do not use a pre-signed URL: Buffer requires the URL to remain reachable until the scheduled post publishes.
3. Create an R2 S3 API token restricted to this bucket with object read/write permission.
4. Record the S3 endpoint, access-key ID, secret access key, bucket name, and public base URL.
5. Add a seven-day bucket lifecycle deletion rule for prefix `buffer/` as an emergency backstop. The application normally deletes each object 48 hours after Buffer confirms `sent`.

Use a dedicated bucket because its objects are publicly readable. Object names are unique per job and approved SHA-256 hash, and the application uploads nothing before Telegram approval.

### Generation providers

Record the same OpenRouter, ElevenLabs, voice, and model settings already used by the successful local mascot-poster generator. The automation worker calls that exact generation service; it is not a mock or a separate simplified renderer.

## 2. Prepare VM 100

Copy or clone this repository to `/home/alexandru/docker/mascot-poster`, then prepare writable persistent paths:

```bash
sudo install -d -o alexandru -g alexandru -m 0750 /srv/mascot-poster
sudo install -d -o alexandru -g alexandru -m 0750 /srv/mascot-poster/output
sudo install -d -o alexandru -g alexandru -m 0750 /srv/mascot-poster/data
sudo install -d -o alexandru -g alexandru -m 0700 /home/alexandru/secrets
cp /home/alexandru/docker/mascot-poster/data/topic_history.json /srv/mascot-poster/data/topic_history.json
docker network inspect n8n-mascot >/dev/null 2>&1 || docker network create n8n-mascot
```

Do not pre-create `/srv/mascot-poster/postgres` with an arbitrary owner. Docker's PostgreSQL entrypoint must initialize and assign its data directory correctly on first start.

## 3. Create the external secrets file

Use `.env.automation.example` only as a list of required names. Create the real file outside the repository:

```bash
install -m 0600 /dev/null /home/alexandru/secrets/mascot-poster.env
nano /home/alexandru/secrets/mascot-poster.env
```

Set `MASCOT_ENV_FILE=/home/alexandru/secrets/mascot-poster.env`, the three `/srv/mascot-poster` paths, fresh random PostgreSQL and internal API values, all Telegram/R2/Buffer values, and all generation-provider values. Never copy this real file into Git, Dockge's stack directory, n8n workflow JSON, or a support message.

Generate local random values without printing them into shell history:

```bash
openssl rand -base64 36
```

## 4. Connect existing n8n privately

Edit `/home/alexandru/docker/n8n/compose.yaml` and attach the n8n service to external network `n8n-mascot`, using the example in `n8n/README.md`. Recreate only n8n and confirm its existing data directory and encryption key remain unchanged:

```bash
cd /home/alexandru/docker/n8n
docker compose --env-file /home/alexandru/secrets/n8n.env config --quiet
docker compose --env-file /home/alexandru/secrets/n8n.env up -d
```

This network change does not require a public n8n webhook or a new firewall opening.

## 5. Validate and start mascot-poster

```bash
cd /home/alexandru/docker/mascot-poster
docker compose --env-file /home/alexandru/secrets/mascot-poster.env config --quiet
docker compose --env-file /home/alexandru/secrets/mascot-poster.env build
docker compose --env-file /home/alexandru/secrets/mascot-poster.env up -d
docker compose --env-file /home/alexandru/secrets/mascot-poster.env ps
```

Expected services are `api`, `worker`, `bot`, `cleanup`, `postgres`, and `searxng`. `api`, `postgres`, and `searxng` should become healthy. Inspect failures without revealing the environment file:

```bash
docker compose --env-file /home/alexandru/secrets/mascot-poster.env logs --tail 100 api worker bot cleanup postgres searxng
```

Test the private DNS path from the existing n8n container:

```bash
docker exec n8n getent hosts mascot-api
```

The exact n8n container name may differ; use `docker compose ps` in the n8n project to find it.

## 6. Import n8n workflows

Follow `n8n/README.md` to create the `Mascot Internal API` Header Auth credential, import the workflows, reconnect that credential in every HTTP node, and run the three manual acceptance steps. Imported workflows are intentionally inactive.

Activate these only after the manual test succeeds:

- `Mascot - Create twice-daily generation jobs`
- `Mascot - Publish newly approved videos`
- `Mascot - Reconcile Buffer delivery`

The daily audit workflow is optional. The generator starts at 07:30 and 15:30; the target publication slots are 09:00 and 17:00 Europe/Bucharest.

## 7. Acceptance test

1. Run the generation workflow manually.
2. Confirm PostgreSQL reports the job as `QUEUED`, then `RUNNING`, then `WAITING_FOR_APPROVAL` through the workflow response or `/status` in Telegram.
3. Inspect the actual MP4 and final social description in Telegram. The description should start with `X vs Y`, contain one concrete supported contrast and a question, and end with three to five real hashtags led by `#pufaila #stiaica`.
4. Confirm `_pipeline/social_description.json` contains the identical `publishable_text`. Recent descriptions are retained in bounded `/srv/mascot-poster/data/description_history.json`; neither file contains credentials.
5. Test one regeneration button and confirm the old approval buttons expire. Script/full regeneration replaces the description; image-only regeneration preserves it.
6. Approve the regenerated video.
7. Run the publish workflow and confirm exactly one Buffer post is created with the Telegram-approved description byte-for-byte, expected video, AI disclosure, and target time.
8. Run reconciliation after publication and confirm the job becomes `PUBLISHED`.
9. Confirm the R2 object is retained initially. Its application cleanup deadline is 48 hours after confirmed publication; the local job directory is retained for 30 days.
10. Test rejection on a second job and confirm no R2 object and no Buffer post are created.

Do not enable unattended posting until both approval and rejection tests behave exactly as described.

## Operations and recovery

Pause generation by deactivating the create workflow. Existing scheduled Buffer posts are not cancelled by pausing n8n; manage them in Buffer if needed. Stop the automation containers without deleting data using:

```bash
docker compose --env-file /home/alexandru/secrets/mascot-poster.env stop api worker bot cleanup
```

Never use `docker compose down -v` for this stack: it can remove named data such as the SearXNG cache, and destructive volume operations require a verified backup first. PostgreSQL, `/srv/mascot-poster/data`, `/srv/mascot-poster/output`, the external secrets file, and the n8n workflow database all need an external backup and restore test before this system is treated as recoverable.

Useful states are `QUEUED`, `RUNNING`, `WAITING_FOR_APPROVAL`, `APPROVED`, `STAGING_MEDIA`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`, `REJECTED`, `MISSED`, `FAILED`, and `CANCELLED`. Approval is bound to the exact MP4 hash. An unapproved job more than three hours past its target becomes `MISSED`; it is never posted later by accident.

Social descriptions are generated only after the final narration timing repair is complete. The checkpoint makes retries resumable, and two description-model failures fall back to the legacy AI script caption with normalized branded hashtags rather than discarding a completed video. Existing submitted or published posts are never edited retroactively.
