"""Alert evaluation service with hysteresis state machine and idempotent Telegram dispatch."""

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from pricewatch.config import settings
from pricewatch.domain.enums import AlertType, NotificationStatus
from pricewatch.domain.models import (
    CanonicalListing,
    NotificationLog,
    PriceQuote,
    Subscription,
)
from pricewatch.logging_setup import get_logger
from pricewatch.repositories.base import BaseSubscriptionRepo, BaseUserRepo
from pricewatch.validation.normalizer import format_paise_to_inr

logger = get_logger("alert_service")


class TelegramBotProtocol(Protocol):
    async def send_message(
        self, chat_id: int, text: str, parse_mode: str = "HTML", disable_web_page_preview: bool = False
    ) -> Any: ...


class AlertService:
    """Evaluates subscriptions and executes idempotent two-phase alert notifications."""

    def __init__(
        self,
        subscription_repo: BaseSubscriptionRepo,
        user_repo: Optional[BaseUserRepo] = None,
        bot: Optional[Any] = None,
    ):
        self.repo = subscription_repo
        self.user_repo = user_repo
        self.bot = bot

    @staticmethod
    def evaluate_alert(
        sub: Subscription,
        quote: PriceQuote,
        hysteresis_rearm_pct: int = 3,
    ) -> Optional[AlertType]:
        """
        Pure function evaluating the 6-scenario alert state machine with hysteresis.
        Returns AlertType if notification should fire, or None if suppressed.
        """
        if not quote.available or quote.price_paise is None:
            return None

        # Scenario 5: Check if price rose enough to re-arm (+3% above target)
        rearm_threshold = int(sub.target_price_paise * (100 + hysteresis_rearm_pct) / 100)
        if quote.price_paise >= rearm_threshold and not sub.alert_rearmed:
            # Price recovered; can be re-armed
            return None

        # Scenario 1: Initial drop to target
        if sub.alert_rearmed and quote.price_paise <= sub.target_price_paise:
            return AlertType.TARGET_REACHED

        # Scenario 2 & 3: Already alerted, evaluate further drop
        if not sub.alert_rearmed and sub.last_alerted_price_paise is not None:
            drop_threshold = int(
                sub.last_alerted_price_paise * (100 - sub.notify_on_further_drop_pct) / 100
            )
            if quote.price_paise <= drop_threshold:
                return AlertType.FURTHER_DROP

        return None

    @staticmethod
    def format_alert_message(
        alert_type: AlertType,
        quote: PriceQuote,
        listing: CanonicalListing,
        sub: Subscription,
    ) -> str:
        """Format HTML alert notification message."""
        price_str = format_paise_to_inr(quote.price_paise)
        target_str = format_paise_to_inr(sub.target_price_paise)
        mrp_str = format_paise_to_inr(quote.mrp_paise) if quote.mrp_paise else None

        if alert_type == AlertType.TARGET_REACHED:
            header = "🎯 <b>PRICE TARGET REACHED!</b>"
        elif alert_type == AlertType.FURTHER_DROP:
            header = "⚡ <b>PRICE DROPPED EVEN FURTHER!</b>"
        else:
            header = "🔔 <b>PRICE ALERT</b>"

        lines = [
            header,
            "",
            f"📦 <b>Product:</b> {listing.product_title}",
        ]
        if listing.variant_title and listing.variant_title != "Default":
            lines.append(f"🏷️ <b>Variant:</b> {listing.variant_title}")

        lines.extend([
            f"💰 <b>Current Price:</b> <code>{price_str}</code>",
            f"🎯 <b>Your Target:</b> <code>{target_str}</code>",
        ])

        if mrp_str and quote.price_paise and quote.mrp_paise and quote.mrp_paise > quote.price_paise:
            discount = int(round((quote.mrp_paise - quote.price_paise) * 100 / quote.mrp_paise))
            lines.append(f"🏷️ <b>MRP:</b> <s>{mrp_str}</s> (<b>{discount}% OFF</b>)")

        if listing.pincode:
            lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")

        lines.extend([
            "",
            f'🔗 <a href="{listing.canonical_url}">Open Store Link</a>',
        ])
        return "\n".join(lines)

    async def process_quote(
        self,
        listing: CanonicalListing,
        quote: PriceQuote,
        observation_id: Optional[int] = None,
    ) -> int:
        """Process price quote against all active subscriptions for a listing."""
        if not listing.id:
            return 0

        subscriptions = await self.repo.get_active_subscriptions_for_listing(listing.id)
        alerts_sent = 0

        for sub in subscriptions:
            # 1. Check for re-arm condition
            rearm_threshold = int(sub.target_price_paise * (100 + settings.HYSTERESIS_REARM_PCT) / 100)
            if quote.price_paise and quote.price_paise >= rearm_threshold and not sub.alert_rearmed:
                await self.repo.update_alert_state(
                    subscription_id=sub.id,
                    last_alerted_price_paise=sub.last_alerted_price_paise,
                    alert_rearmed=True,
                )
                continue

            alert_type = self.evaluate_alert(sub, quote, settings.HYSTERESIS_REARM_PCT)
            if not alert_type:
                continue

            # 2. Phase 1: Outbox row with deterministic idempotency key
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            idempotency_key = f"{sub.id}:{alert_type.value}:{quote.price_paise}:{today_str}"

            notif = NotificationLog(
                subscription_id=sub.id,
                observation_id=observation_id,
                alert_type=alert_type,
                price_paise=quote.price_paise or 0,
                idempotency_key=idempotency_key,
                status=NotificationStatus.PENDING,
            )

            notif_id = await self.repo.log_notification(notif)
            if notif_id is None:
                logger.info("Suppressed duplicate alert via idempotency key", key=idempotency_key)
                continue

            # 3. Phase 2: Telegram Dispatch
            if self.bot:
                text = self.format_alert_message(alert_type, quote, listing, sub)
                try:
                    msg = await self.bot.send_message(
                        chat_id=sub.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
                    # Update subscription alert state
                    await self.repo.update_alert_state(
                        subscription_id=sub.id,
                        last_alerted_price_paise=quote.price_paise,
                        alert_rearmed=False,
                    )
                    alerts_sent += 1
                except Exception as exc:
                    err_msg = str(exc)
                    logger.error("Failed to deliver Telegram alert", chat_id=sub.telegram_id, error=err_msg)
                    if "bot was blocked by the user" in err_msg.lower() or "chat not found" in err_msg.lower():
                        if self.user_repo:
                            await self.user_repo.deactivate_user(sub.telegram_id)
            else:
                # If bot not attached (e.g. headless unit tests), update alert state directly
                await self.repo.update_alert_state(
                    subscription_id=sub.id,
                    last_alerted_price_paise=quote.price_paise,
                    alert_rearmed=False,
                )
                alerts_sent += 1

        return alerts_sent
