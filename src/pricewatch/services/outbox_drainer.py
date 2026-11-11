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
    # Also attach client if repository has Supabase client for alert_outbox table
    client = getattr(repo, "client", None)
    service = OutboxDrainerService(bot=bot, client=client) if client else None
    if service:
        service.start()
    try:
        await drainer.run_loop()
    finally:
        if service:
            await service.stop()


class OutboxDrainerService:
    """Drains public.alert_outbox via the atomic claim_outbox_alerts RPC."""

    def __init__(self, bot: Any, client: Any, rate_limit_per_second: float = 25.0):
        self.bot = bot
        self.client = client
        self.global_limiter = AsyncLimiter(max_rate=rate_limit_per_second, time_period=1.0)
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._drain_loop(), name="outbox_drainer_service")
            logger.info("OutboxDrainerService started (alert_outbox RPC).")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _drain_loop(self) -> None:
        while self._running:
            try:
                if not self.client or not hasattr(self.client, "rpc"):
                    await asyncio.sleep(2.0)
                    continue

                resp = self.client.rpc("claim_outbox_alerts", {"p_batch_size": 50}).execute()
                rows = resp.data or []

                if not rows:
                    await asyncio.sleep(2.0)
                    continue

                await asyncio.gather(*(self._send_single_alert(row) for row in rows))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Outbox drain loop error", error=str(exc))
                await asyncio.sleep(5.0)

    async def _send_single_alert(self, row: dict) -> None:
        from datetime import timedelta
        from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

        alert_id = row["id"]
        chat_id = row["chat_id"]
        text = row["message_html"]
        photo_url = row.get("photo_url")
        markup_data = row.get("reply_markup")
        reply_markup = InlineKeyboardMarkup.de_json(markup_data, self.bot) if markup_data else None

        async with self.global_limiter:
            try:
                if photo_url:
                    await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_url,
                        caption=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                else:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        disable_web_page_preview=False,
                    )
                self.client.table("alert_outbox").delete().eq("id", alert_id).execute()

            except RetryAfter as e:
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=e.retry_after + 1)).isoformat()
                self.client.table("alert_outbox").update({
                    "status": "PENDING",
                    "next_attempt_at": retry_at,
                    "last_error": f"429 RetryAfter {e.retry_after}s",
                }).eq("id", alert_id).execute()

            except (Forbidden, BadRequest) as e:
                self.client.table("alert_outbox").update({
                    "status": "FAILED",
                    "last_error": str(e),
                }).eq("id", alert_id).execute()

            except TelegramError as e:
                backoff_sec = 15 * (2 ** row.get("attempts", 1))
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=backoff_sec)).isoformat()
                self.client.table("alert_outbox").update({
                    "status": "PENDING",
                    "next_attempt_at": retry_at,
                    "last_error": str(e),
                }).eq("id", alert_id).execute()
            except Exception as generic_err:
                logger.warning("Generic alert send error", error=str(generic_err))

