"""Inline keyboard callback query handlers for stepwise onboarding, price charts, and Amul stock."""

from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_amul_category_view,
    format_amul_tracking_confirmed,
    format_stepwise_product_preview,
    format_tracking_confirmation,
)
from pricewatch.bot.keyboards import (
    build_amul_category_keyboard,
    build_amul_product_stock_keyboard,
    build_listing_card_keyboard,
    build_target_price_keyboard,
)
from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.logging_setup import get_logger
from pricewatch.providers.amul import AMUL_CATEGORIES, AmulProvider
from pricewatch.services.chart_service import ChartService
from pricewatch.services.tracker_service import TrackerService

logger = get_logger("callbacks")


async def callback_query_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central callback query router for all inline buttons."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data
    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user_id = query.from_user.id

    try:
        # 1. Stepwise target price selection: tgt:<listing_id>:<target_paise>
        if data.startswith("tgt:"):
            parts = data.split(":")
            listing_id = int(parts[1])
            target_paise = int(parts[2])

            listing, sub = await tracker_service.create_subscription_for_listing(
                telegram_id=user_id,
                listing_id=listing_id,
                target_price_paise=target_paise,
            )
            context.user_data.pop("awaiting_custom_price", None)
            conf_text = format_tracking_confirmation(listing, sub)
            kb = build_listing_card_keyboard(listing_id)
            await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="HTML")
            return

        # 2. Custom target price prompt: tgt_custom:<listing_id>
        if data.startswith("tgt_custom:"):
            parts = data.split(":")
            listing_id = int(parts[1])
            context.user_data["awaiting_custom_price"] = listing_id
            await query.edit_message_text(
                "✏️ <b>Enter your desired target price in INR:</b>\n\n"
                "<i>Just reply with a number (e.g. <code>1200</code> or <code>1599</code>):</i>",
                parse_mode="HTML",
            )
            return

        # 3. View price chart: chart:<listing_id>
        if data.startswith("chart:"):
            parts = data.split(":")
            listing_id = int(parts[1])
            listing = await tracker_service.get_listing(listing_id)
            if not listing:
                await query.edit_message_text("❌ Product listing not found.")
                return

            observations = await tracker_service.get_price_history(listing_id, limit=50)
            subs = await tracker_service.list_user_subscriptions(user_id)
            matching_sub = next((s[0] for s in subs if s[1].id == listing_id), None)
            target_paise = matching_sub.target_price_paise if matching_sub else None

            chart_bytes = ChartService.generate_price_history_chart(
                listing=listing,
                observations=observations,
                target_price_paise=target_paise,
            )
            if not chart_bytes:
                await query.edit_message_text(
                    f"⚠️ Insufficient price history data recorded yet for <b>{listing.product_title}</b>.",
                    parse_mode="HTML",
                )
                return

            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=chart_bytes,
                caption=(
                    f"📊 <b>Price History: {listing.product_title}</b>\n"
                    f"💰 <b>Current:</b> ₹{(listing.last_price_paise or 0)/100:,.0f} | "
                    f"🎯 <b>Target:</b> ₹{(target_paise or 0)/100:,.0f}\n"
                    f"🔗 <a href='{listing.canonical_url}'>Open Store Page</a>"
                ),
                parse_mode="HTML",
            )
            return

        # 4. Untrack confirmation / deletion
        if data.startswith("del:confirm:"):
            listing_id = int(data.split(":")[2])
            await tracker_service.untrack_product(user_id, listing_id)
            await query.edit_message_text(f"🗑️ Successfully removed listing <code>{listing_id}</code> from tracking.", parse_mode="HTML")
            return

        if data == "del:cancel":
            await query.edit_message_text("Tracking unchanged.")
            return

        # 5. Amul Categories Menu
        if data == "amul_menu":
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode_hint = f"📍 Delivery Hub: <code>{user.default_pincode}</code>" if user.default_pincode else "📍 Default Hub: <code>110001</code>"
            text = (
                "🥛 <b>Amul Real-Time Stock & Inventory Tracker</b>\n\n"
                "Pick a category below to browse warehouse inventory and set 1-click restock alerts:\n\n"
                f"{pincode_hint}"
            )
            kb = build_amul_category_keyboard()
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            return

        # 6. Amul Category Product View: amul_cat:<cat_id>
        if data.startswith("amul_cat:"):
            cat_id = data.split(":")[1]
            cat_info = next((c for c in AMUL_CATEGORIES if c["id"] == cat_id), {"label": cat_id.title()})

            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode = user.default_pincode or "110001"

            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(pincode)
            products = await amul_provider.fetch_category_products(cat_id, pincode=pincode)

            user_subs = await tracker_service.list_user_subscriptions(user_id)
            tracked_skus = {s[1].external_variant_id for s in user_subs if s[1].provider_code == "amul"}

            text = format_amul_category_view(cat_info["label"], pincode, substore, products)
            kb = build_amul_product_stock_keyboard(products, tracked_skus)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            return

        # 7. Amul 1-Click Track: amul_track:<sku>
        if data.startswith("amul_track:"):
            sku = data.split(":")[1]
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode = user.default_pincode or "110001"

            amul_provider = AmulProvider()
            quote = await amul_provider.fetch_quote("", sku, sku, pincode=pincode)

            listing = CanonicalListing(
                provider_code="amul",
                provider_tier=1,
                external_product_id=sku,
                external_variant_id=sku,
                pincode=pincode,
                canonical_url=f"https://shop.amul.com/en/browse/product/{sku}",
                product_title=quote.raw_variant_title or sku,
                variant_title="Standard Pack",
                currency="INR",
                last_price_paise=quote.price_paise,
                last_mrp_paise=quote.mrp_paise,
                last_available=quote.available,
                inventory_quantity=quote.inventory_quantity,
                is_monitored=True,
            )
            saved_listing = await tracker_service.listing_repo.get_or_create_listing(listing)
            await tracker_service.sub_repo.create_or_update_subscription(
                Subscription(
                    telegram_id=user_id,
                    listing_id=saved_listing.id,
                    target_price_paise=quote.price_paise or 0,
                    notify_on_restock=True,
                    is_active=True,
                    alert_rearmed=True,
                )
            )

            conf_text = format_amul_tracking_confirmed(
                saved_listing.product_title,
                sku,
                pincode,
                quote.available,
                quote.inventory_quantity or 0,
            )
            kb = build_listing_card_keyboard(saved_listing.id)
            await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="HTML")
            return

        # 8. Amul Untrack: amul_untrack:<sku>
        if data.startswith("amul_untrack:"):
            sku = data.split(":")[1]
            user_subs = await tracker_service.list_user_subscriptions(user_id)
            match = next((s for s in user_subs if s[1].provider_code == "amul" and s[1].external_variant_id == sku), None)
            if match:
                await tracker_service.untrack_product(user_id, match[1].id)
                await query.edit_message_text(f"🗑️ Stopped tracking stock for Amul <code>{sku}</code>.", parse_mode="HTML")
            else:
                await query.edit_message_text(f"❌ Item <code>{sku}</code> not found in your tracking list.", parse_mode="HTML")
            return

        # 9. Cancel button
        if data == "trk:cancel":
            await query.edit_message_text("❌ Product tracking cancelled.")
            context.user_data.pop("pending_track", None)
            context.user_data.pop("pending_track_variants", None)
            context.user_data.pop("awaiting_custom_price", None)
            return

        # 10. Variant selection button (trk:v:<variant_id>)
        if data.startswith("trk:v:"):
            parts = data.split(":")
            variant_id = parts[2]

            # Case A: Legacy /track with target price pre-set
            pending_track = context.user_data.get("pending_track")
            if pending_track:
                variants_dict = pending_track.get("variants", {})
                selected_variant = variants_dict.get(variant_id)
                if not selected_variant:
                    await query.edit_message_text("❌ Selected variant could not be found.")
                    return

                target_price_paise = pending_track.get("target_price_paise", 0)
                pincode = pending_track.get("pincode", "")
                domain = urlparse(selected_variant.canonical_url).hostname or "unknown"
                provider_code = f"shopify:{domain.replace('www.', '')}"

                listing, sub = await tracker_service.track_pinned_variant(
                    telegram_id=user_id,
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
                kb = build_listing_card_keyboard(listing.id)
                await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="HTML")
                context.user_data.pop("pending_track", None)
                return

            # Case B: Stepwise link inspection variant selection
            pending_variants = context.user_data.get("pending_track_variants")
            if pending_variants:
                variants_dict = pending_variants.get("variants", {})
                selected_variant = variants_dict.get(variant_id)
                if not selected_variant:
                    await query.edit_message_text("❌ Selected variant could not be found.")
                    return

                domain = urlparse(selected_variant.canonical_url).hostname or "unknown"
                provider_code = f"shopify:{domain.replace('www.', '')}"

                listing_to_create = CanonicalListing(
                    provider_code=provider_code,
                    provider_tier=1,
                    external_product_id=variant_id,
                    external_variant_id=variant_id,
                    pincode="",
                    canonical_url=selected_variant.canonical_url,
                    product_title=selected_variant.variant_title,
                    variant_title=selected_variant.variant_title,
                    currency="INR",
                    last_price_paise=selected_variant.price_paise,
                    last_mrp_paise=selected_variant.mrp_paise,
                    last_available=selected_variant.available,
                    is_monitored=True,
                )
                saved_listing = await tracker_service.listing_repo.get_or_create_listing(listing_to_create)
                context.user_data["awaiting_custom_price"] = saved_listing.id
                context.user_data.pop("pending_track_variants", None)

                preview_text = format_stepwise_product_preview(saved_listing)
                kb = build_target_price_keyboard(
                    listing_id=saved_listing.id,
                    current_price_paise=saved_listing.last_price_paise or 0,
                )
                await query.edit_message_text(preview_text, reply_markup=kb, parse_mode="HTML")
                return

            await query.edit_message_text("⚠️ Selection expired. Please paste the product link again.")

    except Exception as exc:
        logger.exception("Failed to process callback query", data=data, error=str(exc))
        await query.edit_message_text(f"❌ Error: {exc}")
