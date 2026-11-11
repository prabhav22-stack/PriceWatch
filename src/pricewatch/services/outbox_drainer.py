"""Transactional outbox drainer service with token-bucket rate limiting (25 msg/s).

Ensures all background workers (Render pollers, GitHub Actions ephemeral runners)
can emit price alerts into Postgres without initializing Telegram Bot applications.
The always-on Render web server drains pending alerts at a safe rate to avoid Telegram 429 errors.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from aiolimiter import AsyncLimiter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pricewatch.domain.enums import AlertType, NotificationStatus
from pricewatch.domain.models import CanonicalListing, NotificationLog, PriceQuote, Subscription
from pricewatch.logging_setup import get_logger
from pricewatch.repositories.base import BaseSubscriptionRepo
from pricewatch.services.alert_service import AlertService

logger = get_logger("outbox_drainer")


class OutboxDrainer:
    """Drains pending notifications from the transactional outbox table at <= 25 msg/s."""

    def __init__(
        self,
        repo: BaseSubscriptionRepo,
        bot: Any,
        rate_limit_per_second: float = 25.0,
        drain_interval_seconds: float = 2.0,
    ):
        self.repo = repo
        self.bot = bot
        self.limiter = AsyncLimiter(rate_limit_per_second, 1.0)
        self.drain_interval = drain_interval_seconds
        self._running = False

    async def drain_batch(self, limit: int = 50) -> int:
        """Fetch and dispatch a batch of pending alerts."""
        if not hasattr(self.repo, "get_pending_notifications") or not self.bot:
            return 0

        pending_items = await self.repo.get_pending_notifications(limit=limit)
        if not pending_items:
            return 0

        sent_count = 0
        for notif, sub, listing in pending_items:
            async with self.limiter:
                try:
                    quote = PriceQuote(
                        external_product_id=listing.external_product_id,
                        external_variant_id=listing.external_variant_id,
                        price_paise=notif.price_paise,
                        available=True,
                        currency="INR",
                        extraction_method="outbox",
                    )
                    text = AlertService.format_alert_message(notif.alert_type, quote, listing, sub)
                    reply_markup = None
                    if listing.canonical_url and listing.canonical_url.startswith("http"):
                        btn_label = "🛍️ Order on Amul Now" if listing.provider_code == "amul" else "🛒 View Product"
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton(btn_label, url=listing.canonical_url)]
                        ])

                    msg = await self.bot.send_message(
                        chat_id=sub.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        disable_web_page_preview=False,
                    )
                    msg_id = getattr(msg, "message_id", None)
                    await self.repo.mark_notification_sent(notif.id, telegram_message_id=msg_id)
                    sent_count += 1
                except Exception as exc:
                    err_str = str(exc)
                    logger.warning("Failed to send outbox notification", notif_id=notif.id, error=err_str)
                    is_retryable = "429" in err_str or "timeout" in err_str.lower() or "network" in err_str.lower()
                    await self.repo.mark_notification_failed(
                        notification_id=notif.id,
                        error_detail=err_str,
                        retry_count=notif.retry_count + 1,
                        retryable=is_retryable,
                    )
        return sent_count

    async def run_loop(self) -> None:
        """Continuous background loop polling outbox."""
        self._running = True
        logger.info("Outbox drainer service started (limit: 25 msg/s)")
        while self._running:
            try:
                await self.drain_batch()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Outbox drainer error in loop", error=str(exc))
            await asyncio.sleep(self.drain_interval)


async def run_outbox_drainer(
    repo: BaseSubscriptionRepo, bot: Any, interval_seconds: float = 2.0
) -> None:
    drainer = OutboxDrainer(repo=repo, bot=bot, drain_interval_seconds=interval_seconds)
    await drainer.run_loop()
