from __future__ import annotations

import asyncio

from app.automation.runtime import build_job_service
from app.automation.settings import get_automation_settings
from app.automation.telegram_bot import TelegramApprovalBot
from app.automation.telegram_client import TelegramClient


async def run() -> None:
    settings = get_automation_settings()
    if settings.telegram_bot_token is None:
        raise RuntimeError("AUTOMATION_TELEGRAM_BOT_TOKEN is required")
    if settings.telegram_allowed_user_id is None:
        raise RuntimeError("AUTOMATION_TELEGRAM_ALLOWED_USER_ID is required")
    if settings.telegram_review_chat_id is None:
        raise RuntimeError("AUTOMATION_TELEGRAM_REVIEW_CHAT_ID is required")
    client = TelegramClient(settings.telegram_bot_token.get_secret_value())
    bot = TelegramApprovalBot(
        build_job_service(),
        client,
        allowed_user_id=settings.telegram_allowed_user_id,
        review_chat_id=settings.telegram_review_chat_id,
    )
    try:
        await bot.run_forever(settings.telegram_poll_seconds)
    finally:
        await client.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
