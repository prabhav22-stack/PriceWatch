"""Web server entry point for Render hosting the Telegram webhook and /healthz endpoint."""

import argparse
import asyncio
import os
import sys

from pricewatch.bot.app import create_telegram_app
from pricewatch.config import settings
from pricewatch.logging_setup import get_logger, setup_logging
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.repositories.supabase_repo import SupabaseRepository
from pricewatch.services.tracker_service import TrackerService

logger = get_logger("web_server")


def main():
    parser = argparse.ArgumentParser(description="PriceWatch Telegram bot web server.")
    parser.add_argument(
        "--polling",
        action="store_true",
        help="Run bot in local polling mode instead of webhook mode",
    )
    args = parser.parse_args()

    setup_logging(log_level=settings.LOG_LEVEL)

    # Initialize repository (Supabase if configured, otherwise MemoryRepository)
    if settings.SUPABASE_URL and (settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN):
        try:
            repo = SupabaseRepository()
            logger.info("Connected to Supabase PostgreSQL repository")
        except Exception as exc:
            logger.warning("Supabase connection failed, falling back to MemoryRepository", error=str(exc))
            repo = MemoryRepository()
    else:
        repo = MemoryRepository()
    tracker_service = TrackerService(
        listing_repo=repo,
        subscription_repo=repo,
        user_repo=repo,
    )

    app = create_telegram_app(tracker_service=tracker_service)

    port = int(os.getenv("PORT", "8000"))
    is_polling = args.polling or settings.APP_ENV == "development" and not settings.WEBHOOK_BASE_URL

    if is_polling:
        logger.info("Starting PriceWatch bot in local long-polling mode...")
        app.run_polling(drop_pending_updates=True)
    else:
        webhook_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/webhook"
        logger.info(
            "Starting PriceWatch bot in webhook mode...",
            port=port,
            webhook_url=webhook_url,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=webhook_url,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
