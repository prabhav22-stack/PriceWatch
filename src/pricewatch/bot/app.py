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

from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import (
    amul_command_handler,
    help_handler,
    history_command_handler,
    list_handler,
    pincode_handler,
    plain_text_handler,
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
    app.add_handler(CommandHandler("amul", amul_command_handler))
    app.add_handler(CommandHandler("products", amul_command_handler))
    app.add_handler(CommandHandler("history", history_command_handler))

    # Catch /untrack_123 and /history_123 shorthand commands
    app.add_handler(MessageHandler(filters.Regex(r"^/untrack_\d+"), untrack_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/history_\d+"), history_command_handler))

    # Catch plain text: conversational URL pasting & custom target price replies
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_text_handler))

    # Central Callback Query Handler (pills, variant buttons, chart, Amul)
    app.add_handler(CallbackQueryHandler(callback_query_dispatcher))

    return app
