"""Telegram Application factory and handler registration."""

from typing import Optional
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from pricewatch.bot.handlers.callbacks import variant_callback_handler
from pricewatch.bot.handlers.commands import (
    help_handler,
    list_handler,
    pincode_handler,
    start_handler,
    status_handler,
    track_handler,
    untrack_handler,
)
from pricewatch.config import settings
from pricewatch.services.tracker_service import TrackerService


def create_telegram_app(
    tracker_service: TrackerService,
    bot_token: Optional[str] = None,
) -> Application:
    """Build and configure the python-telegram-bot application."""
    token = bot_token or settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing")

    builder = ApplicationBuilder().token(token)
    # Enable asynchronous rate limiting to respect Telegram's 30 msgs/sec global limit
    builder.rate_limiter(AIORateLimiter())

    app = builder.build()

    # Inject domain service into bot_data
    app.bot_data["tracker_service"] = tracker_service

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("track", track_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("untrack", untrack_handler))
    app.add_handler(CommandHandler("pincode", pincode_handler))
    app.add_handler(CommandHandler("status", status_handler))

    # Catch /untrack_123 shorthand commands
    app.add_handler(MessageHandler(filters.Regex(r"^/untrack_\d+"), untrack_handler))

    # Register Callback Query Handlers (variant buttons)
    app.add_handler(CallbackQueryHandler(variant_callback_handler))

    return app
