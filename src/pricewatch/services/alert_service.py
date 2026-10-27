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
        self._cycle_counts: dict[int, int] = {}
        self._last_alerted_ts: dict[int, float] = {}
        self._last_alerted_qty: dict[int, int] = {}

    @staticmethod
    def evaluate_alert(
        sub: Subscription,
        quote: PriceQuote,
        hysteresis_rearm_pct: int = 3,
        listing: Optional[CanonicalListing] = None,
    ) -> Optional[AlertType]:
        """
        Pure function evaluating alert state machine with hysteresis.
        Supports target price drops, further drops, significant flash drops, and Amul stock restocks.
        """
        # 1. Amul Stock Restock Logic (Quantity & Availability focused)
        if listing and listing.provider_code == "amul":
            if quote.available and (quote.inventory_quantity is None or quote.inventory_quantity > 0):
                if sub.alert_rearmed:
                    return AlertType.AMUL_RESTOCK
            return None

        if not quote.available or quote.price_paise is None:
            return None

        # Scenario 5: Check if price rose enough to re-arm (+3% above target)
        rearm_threshold = int(sub.target_price_paise * (100 + hysteresis_rearm_pct) / 100)
        if quote.price_paise >= rearm_threshold and not sub.alert_rearmed:
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

        # Significant Price Drop (>= 10% drop from last price, even if above target)
        if listing and listing.last_price_paise and sub.alert_rearmed:
            ten_pct_drop = int(listing.last_price_paise * 0.90)
            if quote.price_paise <= ten_pct_drop:
                return AlertType.SIGNIFICANT_DROP

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

        if alert_type == AlertType.AMUL_RESTOCK:
            qty_str = (
                f"<b>{quote.inventory_quantity} units</b> available"
                if quote.inventory_quantity is not None
                else "In Stock"
            )
            lines = [
                "🥛 <b>AMUL PRODUCT BACK IN STOCK!</b>",
                "",
                f'📦 <b>Product:</b> <a href="{listing.canonical_url}">{listing.product_title}</a>',
                f"🔢 <b>Available Stock:</b> {qty_str}",
                f"💰 <b>Price:</b> <code>{price_str}</code>",
            ]
            if listing.pincode:
                lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")
            lines.extend([
                "",
                f'🔗 <a href="{listing.canonical_url}">Order on Amul Shop Now</a>',
            ])
            return "\n".join(lines)

        if alert_type == AlertType.AMUL_STOCK_DECREASE:
            prev_qty = sub.last_alerted_price_paise or 0
            curr_qty = quote.inventory_quantity or 0
            diff = prev_qty - curr_qty if prev_qty > curr_qty else 0
            lines = [
                "📉 <b>AMUL STOCK DECREASING!</b>",
                "",
                f'📦 <b>Product:</b> <a href="{listing.canonical_url}">{listing.product_title}</a>',
                f"🔢 <b>Stock Update:</b> <code>{prev_qty}</code> ➔ <b>{curr_qty} units remaining</b> (-{diff} sold)",
                f"💰 <b>Price:</b> <code>{price_str}</code>",
            ]
            if listing.pincode:
                lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")
            lines.extend([
                "",
                f'🔗 <a href="{listing.canonical_url}">Order on Amul Shop Now</a>',
            ])
            return "\n".join(lines)

        if alert_type == AlertType.AMUL_REPEAT_REMINDER:
            qty_str = (
                f"<b>{quote.inventory_quantity} units</b> available"
                if quote.inventory_quantity is not None
                else "In Stock"
            )
            lines = [
                "🥛 <b>AMUL PRODUCT STILL IN STOCK!</b>",
                "",
                f'📦 <b>Product:</b> <a href="{listing.canonical_url}">{listing.product_title}</a>',
                f"🔢 <b>Current Stock:</b> {qty_str}",
                f"💰 <b>Price:</b> <code>{price_str}</code>",
            ]
            if listing.pincode:
                lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")
            lines.extend([
                "",
                f'🔗 <a href="{listing.canonical_url}">Order on Amul Shop Now</a>',
            ])
            return "\n".join(lines)

        if alert_type == AlertType.AMUL_OUT_OF_STOCK:
            lines = [
                "🔴 <b>AMUL PRODUCT OUT OF STOCK</b>",
                "",
                f'📦 <b>Product:</b> <a href="{listing.canonical_url}">{listing.product_title}</a>',
                "All units have sold out in this warehouse drop.",
                "The bot will automatically notify you on the next restock!",
            ]
            if listing.pincode:
                lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")
            return "\n".join(lines)

        if alert_type == AlertType.TARGET_REACHED:
            header = "🎯 <b>PRICE TARGET REACHED!</b>"
        elif alert_type == AlertType.FURTHER_DROP:
            header = "⚡ <b>PRICE DROPPED EVEN FURTHER!</b>"
        elif alert_type == AlertType.SIGNIFICANT_DROP:
            header = "🔥 <b>SIGNIFICANT PRICE DROP DETECTED!</b>"
        else:
            header = "🔔 <b>PRICE ALERT</b>"

        lines = [
            header,
            "",
            f"📦 <b>Product:</b> {listing.product_title}",
        ]
        if listing.variant_title and listing.variant_title != "Default":
            lines.append(f"🏷️ <b>Variant:</b> {listing.variant_title}")

        if alert_type == AlertType.SIGNIFICANT_DROP and listing.last_price_paise and quote.price_paise:
            drop_pct = int(round((listing.last_price_paise - quote.price_paise) * 100 / listing.last_price_paise))
            prev_str = format_paise_to_inr(listing.last_price_paise)
            lines.append(f"📉 <b>Dropped by {drop_pct}%</b> (from {prev_str} ➔ {price_str})")

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
            if (
                listing.provider_code == "amul"
                and (not quote.available or (quote.inventory_quantity is not None and quote.inventory_quantity <= 0))
            ):
                if not sub.alert_rearmed:
                    self._cycle_counts[sub.id] = 0
                    await self.repo.update_alert_state(
                        subscription_id=sub.id,
                        last_alerted_price_paise=None,
                        alert_rearmed=True,
                    )
                continue

            rearm_threshold = int(sub.target_price_paise * (100 + settings.HYSTERESIS_REARM_PCT) / 100)
            if quote.price_paise and quote.price_paise >= rearm_threshold and not sub.alert_rearmed:
                await self.repo.update_alert_state(
                    subscription_id=sub.id,
                    last_alerted_price_paise=sub.last_alerted_price_paise,
                    alert_rearmed=True,
                )
                continue

            alert_type = None
            now_ts = datetime.now(timezone.utc).timestamp()
            if listing.provider_code == "amul":
                if quote.available and (quote.inventory_quantity is None or quote.inventory_quantity > 0):
                    if sub.alert_rearmed:
                        alert_type = AlertType.AMUL_RESTOCK
                        self._cycle_counts[sub.id] = 1
                        self._last_alerted_ts[sub.id] = now_ts
                        self._last_alerted_qty[sub.id] = quote.inventory_quantity or 0
                    else:
                        prev_qty = self._last_alerted_qty.get(sub.id, sub.last_alerted_price_paise)
                        curr_qty = quote.inventory_quantity
                        user = await self.user_repo.get_or_create_user(sub.telegram_id) if self.user_repo else None
                        max_alerts = user.max_notify_count if user is not None else 5
                        cycle_count = self._cycle_counts.get(sub.id, 1)

                        # Check if eligible for repeat notifications (max_alerts == 0 means until stock runs out)
                        if max_alerts == 0 or cycle_count < max_alerts:
                            # 1. Did stock decrease? Immediate alert!
                            if prev_qty is not None and curr_qty is not None and curr_qty < prev_qty:
                                alert_type = AlertType.AMUL_STOCK_DECREASE
                                self._cycle_counts[sub.id] = cycle_count + 1
                                self._last_alerted_ts[sub.id] = now_ts
                                self._last_alerted_qty[sub.id] = curr_qty
                            # 2. Did >= 120s elapse since last alert? Periodic in-stock reminder!
                            elif now_ts - self._last_alerted_ts.get(sub.id, 0) >= 120:
                                alert_type = AlertType.AMUL_REPEAT_REMINDER
                                self._cycle_counts[sub.id] = cycle_count + 1
                                self._last_alerted_ts[sub.id] = now_ts
                                self._last_alerted_qty[sub.id] = curr_qty or 0
            else:
                alert_type = self.evaluate_alert(sub, quote, settings.HYSTERESIS_REARM_PCT, listing=listing)

            if not alert_type:
                continue

            # 2. Phase 1: Outbox row with deterministic idempotency key
            if alert_type in (AlertType.AMUL_RESTOCK, AlertType.AMUL_STOCK_DECREASE, AlertType.AMUL_REPEAT_REMINDER):
                idempotency_key = f"{sub.id}:{alert_type.value}:{quote.inventory_quantity}:{int(now_ts // 60)}"
            else:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                price_for_key = quote.price_paise or quote.inventory_quantity or 0
                idempotency_key = f"{sub.id}:{alert_type.value}:{price_for_key}:{today_str}"

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
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                reply_markup = None
                if listing.canonical_url and listing.canonical_url.startswith("http"):
                    reply_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛍️ Order on Amul Now", url=listing.canonical_url)]
                    ])
                try:
                    msg = await self.bot.send_message(
                        chat_id=sub.telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        disable_web_page_preview=False,
                    )
                    # Update subscription alert state: for Amul, store inventory quantity to track decreases
                    alerted_val = quote.inventory_quantity if listing.provider_code == "amul" else quote.price_paise
                    await self.repo.update_alert_state(
                        subscription_id=sub.id,
                        last_alerted_price_paise=alerted_val,
                        alert_rearmed=False,
                    )
                    alerts_sent += 1

                    # Check user tracking style ("once" untracks automatically) & auto-order trigger
                    if self.user_repo:
                        try:
                            user = await self.user_repo.get_or_create_user(sub.telegram_id)
                            if user.tracking_style == "once":
                                await self.repo.delete_subscription(sub.telegram_id, sub.listing_id)

                            if (
                                alert_type == AlertType.AMUL_RESTOCK
                                and user.auto_order_enabled
                                and listing.external_variant_id in (user.auto_order_skus or [])
                            ):
                                from pricewatch.services.amul_auto_order import AmulAutoOrderService
                                ao_svc = AmulAutoOrderService()
                                ao_res = await ao_svc.execute_restock_auto_order(
                                    phone=user.auto_order_phone or "",
                                    auth_token=user.auto_order_auth_token or "",
                                    sku=listing.external_variant_id,
                                    pincode=listing.pincode or "842002",
                                    address_id=user.auto_order_address_id,
                                )
                                ao_text = (
                                    "⚡ <b>AUTO-ORDER TRIGGERED!</b>\n\n"
                                    f"📦 <b>Product:</b> {listing.product_title}\n"
                                    f"🏷️ <b>SKU:</b> <code>{listing.external_variant_id}</code>\n"
                                    f"📋 <b>Result:</b> {ao_res['message']}"
                                )
                                await self.bot.send_message(chat_id=sub.telegram_id, text=ao_text, parse_mode="HTML")
                        except Exception as ao_err:
                            logger.warning("Error evaluating auto-order in alert service", error=str(ao_err))
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
