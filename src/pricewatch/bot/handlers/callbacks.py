"""Inline keyboard callback query handlers."""

from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import format_tracking_confirmation
from pricewatch.logging_setup import get_logger
from pricewatch.services.tracker_service import TrackerService

logger = get_logger("callbacks")


async def variant_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle variant selection button clicks (trk:v:<variant_id>)."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    data = query.data
    if data == "trk:cancel":
        await query.edit_message_text("❌ Product tracking cancelled.")
        context.user_data.pop("pending_track", None)
        return

    if not data.startswith("trk:v:"):
        return

    parts = data.split(":")
    variant_id = parts[2]

    pending = context.user_data.get("pending_track")
    if not pending:
        await query.edit_message_text(
            "⚠️ Tracking session expired. Please send the <code>/track</code> command again.",
            parse_mode="HTML",
        )
        return

    variants_dict = pending.get("variants", {})
    selected_variant = variants_dict.get(variant_id)
    if not selected_variant:
        await query.edit_message_text("❌ Selected variant could not be found.")
        return

    target_price_paise = pending.get("target_price_paise", 0)
    pincode = pending.get("pincode", "")
    tracker_service: TrackerService = context.bot_data["tracker_service"]

    try:
        from urllib.parse import urlparse
        domain = urlparse(selected_variant.canonical_url).hostname or "unknown"
        provider_code = f"shopify:{domain.replace('www.', '')}"

        listing, sub = await tracker_service.track_pinned_variant(
            telegram_id=query.from_user.id,
            provider_code=provider_code,
            external_product_id=parts[2],
            variant_id=variant_id,
            product_title=selected_variant.variant_title,
            variant_title=selected_variant.variant_title,
            canonical_url=selected_variant.canonical_url,
            target_price_paise=target_price_paise,
            pincode=pincode,
            last_price_paise=selected_variant.price_paise,
            last_mrp_paise=selected_variant.mrp_paise,
            available=selected_variant.available,
        )

        conf_text = format_tracking_confirmation(listing, sub)
        await query.edit_message_text(conf_text, parse_mode="HTML")
        context.user_data.pop("pending_track", None)

    except Exception as exc:
        logger.exception("Failed to track pinned variant", error=str(exc))
        await query.edit_message_text(f"❌ Failed to track variant: {exc}")
