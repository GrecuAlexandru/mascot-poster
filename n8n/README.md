# n8n Workflows

This directory contains pre-built n8n workflow JSON files for the automated video generation pipeline.

## Workflows

1. **generate_video.json** — Cron-triggered job creation (every day at 09:00 and 17:00)
2. **approval_flow.json** — Webhook receiver for completion notifications, sends Telegram approval message
3. **publish_video.json** — Webhook receiver for approval, publishes via API, sends notification
4. **analytics_collection.json** — Periodic metrics collection and summary (every 6 hours)

## Setup

1. Import each workflow JSON into n8n (Import from File)
2. Configure environment variables in n8n:
   - `TELEGRAM_CHAT_ID` — Telegram chat to send notifications
3. Configure the Python API URL (default: `http://api:8000`)
4. Activate workflows after verifying connections

## URL Configuration

All workflows assume the Python API is accessible at `http://api:8000`. Adjust if using a different host.
