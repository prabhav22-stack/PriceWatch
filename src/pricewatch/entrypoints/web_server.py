"""Web server entry point for Render hosting the Telegram webhook and /healthz endpoint."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure src/ is in sys.path
root_dir = Path(__file__).resolve().parents[3]
src_dir = root_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import tornado.ioloop
import tornado.web
from telegram import Update

from pricewatch.bot.app import create_telegram_app
from pricewatch.bot.commands_menu import configure_bot_menu_button
from pricewatch.config import settings
from pricewatch.logging_setup import get_logger, setup_logging
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.repositories.supabase_repo import SupabaseRepository
from pricewatch.services.amul_poller import run_amul_poller
from pricewatch.services.tracker_service import TrackerService

logger = get_logger("web_server")


class HealthHandler(tornado.web.RequestHandler):
    """Health check endpoint for Render keep-alive and uptime probes."""

    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "service": "pricewatch"})


class TelegramWebhookHandler(tornado.web.RequestHandler):
    """Receives HTTPS POST updates from Telegram Bot API."""

    def initialize(self, ptb_app):
        self.ptb_app = ptb_app

    async def post(self):
        # Validate secret token header if configured
        if settings.TELEGRAM_WEBHOOK_SECRET:
            token = self.request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning("Rejected webhook request with invalid secret token")
                self.set_status(403)
                self.write("Forbidden")
                return

        try:
            payload = json.loads(self.request.body.decode("utf-8"))
            update = Update.de_json(data=payload, bot=self.ptb_app.bot)
            await self.ptb_app.update_queue.put(update)
            self.set_status(200)
            self.write("OK")
        except Exception as exc:
            logger.error("Failed to process Telegram webhook update", error=str(exc))
            self.set_status(400)
            self.write("Bad Request")


async def run_server_async(port: int, webhook_url: str) -> None:
    """Initialize bot, set webhook, and start Tornado HTTP server."""
    # Initialize repository (Supabase in production, MemoryRepository fallback)
    if settings.SUPABASE_URL and (settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN):
        try:
            repo = SupabaseRepository()
            logger.info("Connected to Supabase PostgreSQL repository")
        except Exception as exc:
            logger.warning("Supabase connection failed, falling back to MemoryRepository", error=str(exc))
            repo = MemoryRepository()
    else:
        repo = MemoryRepository()

    ptb_app = None
    amul_task = None

    # Check if bot token is configured
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            tracker_service = TrackerService(
                listing_repo=repo,
                subscription_repo=repo,
                user_repo=repo,
            )
            ptb_app = create_telegram_app(tracker_service=tracker_service)
            await ptb_app.initialize()
            await ptb_app.start()
            try:
                await configure_bot_menu_button(ptb_app.bot)
            except Exception as menu_exc:
                logger.warning("Failed to configure bot menu button", error=str(menu_exc))

            # Register webhook if URL is valid (not localhost)
            if webhook_url and not ("localhost" in webhook_url or "127.0.0.1" in webhook_url):
                try:
                    logger.info("Setting Telegram webhook...", webhook_url=webhook_url)
                    await ptb_app.bot.set_webhook(
                        url=webhook_url,
                        secret_token=settings.TELEGRAM_WEBHOOK_SECRET or None,
                        drop_pending_updates=True,
                    )
                    logger.info("Telegram webhook successfully registered")
                except Exception as wh_exc:
                    logger.error("Failed to set Telegram webhook", error=str(wh_exc), url=webhook_url)
            else:
                logger.warning("Skipping Telegram webhook registration (localhost or empty webhook URL)", webhook_url=webhook_url)

            # Launch high-frequency Amul stock poller (Tier 1: 30s)
            amul_task = asyncio.create_task(
                run_amul_poller(repo=repo, bot=ptb_app.bot, interval_seconds=settings.AMUL_CHECK_INTERVAL_SECONDS)
            )
        except Exception as bot_exc:
            logger.error("Failed to initialize Telegram application", error=str(bot_exc))
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Web server will serve healthz only until token is configured.")

    # Configure Tornado HTTP routes
    handlers = [
        (r"/healthz", HealthHandler),
        (r"/", HealthHandler),
    ]
    if ptb_app:
        handlers.append((r"/webhook", TelegramWebhookHandler, dict(ptb_app=ptb_app)))

    tornado_app = tornado.web.Application(handlers)
    tornado_app.listen(port, address="0.0.0.0")
    logger.info("PriceWatch HTTP server listening on 0.0.0.0", port=port)

    # Keep running
    try:
        await asyncio.Event().wait()
    finally:
        logger.info("Shutting down bot and web server...")
        if amul_task:
            amul_task.cancel()
        if ptb_app:
            await ptb_app.stop()
            await ptb_app.shutdown()


def main():
    parser = argparse.ArgumentParser(description="PriceWatch Telegram bot web server.")
    parser.add_argument(
        "--polling",
        action="store_true",
        help="Run bot in local polling mode instead of webhook mode",
    )
    args = parser.parse_args()

    setup_logging(log_level=settings.LOG_LEVEL)

    port = int(os.getenv("PORT", "8000"))
    is_polling = args.polling or (settings.APP_ENV == "development" and not settings.WEBHOOK_BASE_URL)

    if is_polling:
        logger.info("Starting PriceWatch bot in local long-polling mode...")
        # Local polling mode
        repo = SupabaseRepository() if settings.SUPABASE_URL else MemoryRepository()
        svc = TrackerService(repo, repo, repo)
        app = create_telegram_app(svc)
        app.run_polling(drop_pending_updates=True)
    else:
        webhook_base = settings.WEBHOOK_BASE_URL or f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}"
        webhook_url = f"{webhook_base.rstrip('/')}/webhook"
        logger.info("Starting PriceWatch in webhook mode", port=port, webhook_url=webhook_url)
        asyncio.run(run_server_async(port=port, webhook_url=webhook_url))


if __name__ == "__main__":
    main()
