"""Telegram command handlers (/start, /help, /track, /list, /untrack, /pincode, /status, /amul, /history)."""

import re
from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_amul_category_menu,
    format_amul_tracking_confirmed,
    format_help_message,
    format_stepwise_product_preview,
    format_subscription_list,
    format_tracking_confirmation,
    format_welcome_message,
)
from pricewatch.bot.keyboards import (
    build_amul_category_keyboard,
    build_listing_card_keyboard,
    build_target_price_keyboard,
    build_variant_selection_keyboard,
)
from pricewatch.domain.exceptions import VariantAmbiguousError
from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.providers.amul import AmulProvider
from pricewatch.providers.base import ProviderRegistry
from pricewatch.services.chart_service import ChartService
from pricewatch.services.tracker_service import TrackerService
from pricewatch.validation.normalizer import parse_inr_to_paise


_PINCODE_REGEX = re.compile(r"^\d{6}$")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command, including deeplinks like /start track_<sku> and /start untrack_<sku>."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = update.effective_user
    db_user = await tracker_service.get_or_register_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    # Check for deeplink payload: e.g. /start track_WPCCP01_01
    if context.args:
        payload = context.args[0].strip()
        if payload.startswith("track_") or payload.startswith("fav_"):
            sku = payload.replace("track_", "").replace("fav_", "")
            pincode = db_user.default_pincode or "842002"
            provider = AmulProvider()
            quote = await provider.fetch_quote("", sku, sku, pincode=pincode)

            listing = CanonicalListing(
                provider_code="amul",
                provider_tier=1,
                external_product_id=sku,
                external_variant_id=sku,
                pincode=pincode,
                canonical_url=f"https://shop.amul.com/en/product/{sku}",
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
            is_in_stock = quote.available and (quote.inventory_quantity is None or quote.inventory_quantity > 0)
            await tracker_service.sub_repo.create_or_update_subscription(
                Subscription(
                    telegram_id=user.id,
                    listing_id=saved_listing.id,
                    target_price_paise=quote.price_paise or 0,
                    notify_on_restock=True,
                    is_active=True,
                    alert_rearmed=not is_in_stock,
                    last_alerted_price_paise=quote.price_paise if is_in_stock else None,
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
            await update.effective_message.reply_html(conf_text, reply_markup=kb)
            return

        if payload.startswith("untrack_"):
            sku = payload.replace("untrack_", "")
            subs = await tracker_service.list_user_subscriptions(user.id)
            match = next((s for s in subs if s[1].provider_code == "amul" and s[1].external_variant_id == sku), None)
            if match:
                await tracker_service.untrack_product(user.id, match[1].id)
                await update.effective_message.reply_html(f"🗑️ Stopped tracking stock for Amul <code>{sku}</code>.")
            else:
                await update.effective_message.reply_html(f"❌ Item <code>{sku}</code> not found in your tracking list.")
            return

    text = format_welcome_message(user.first_name or "there")
    await update.effective_message.reply_html(text)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.effective_message:
        return
    text = format_help_message()
    await update.effective_message.reply_html(text)


async def track_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /track <url> <target_price> [pincode]."""
    if not update.effective_user or not update.effective_message:
        return

    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_html(
            "⚠️ <b>Usage:</b> <code>/track &lt;url&gt; &lt;target_price&gt; [pincode]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/track https://nakpro.com/products/impact-whey-protein 1200</code>"
        )
        return

    url = args[0].strip()
    raw_target = args[1].strip()
    target_price_paise = parse_inr_to_paise(raw_target)

    if not target_price_paise or target_price_paise <= 0:
        await update.effective_message.reply_html(
            "❌ <b>Invalid target price!</b> Please enter a valid number (e.g. <code>1200</code> or <code>₹1,200</code>)."
        )
        return

    pincode = args[2].strip() if len(args) >= 3 else None
    if pincode and not _PINCODE_REGEX.match(pincode):
        await update.effective_message.reply_html(
            "❌ <b>Invalid pincode!</b> Indian pincodes must be exactly 6 digits (e.g. <code>842002</code>)."
        )
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    status_msg = await update.effective_message.reply_text("🔍 Inspecting product URL...")

    try:
        listing, sub = await tracker_service.track_url(
            telegram_id=update.effective_user.id,
            url=url,
            target_price_paise=target_price_paise,
            pincode=pincode,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )
        conf_text = format_tracking_confirmation(listing, sub)
        await status_msg.edit_text(conf_text, parse_mode="HTML")

    except VariantAmbiguousError as amb_err:
        # Product has multiple variants; prompt user to select with inline buttons
        variants = amb_err.variants
        context.user_data["pending_track"] = {
            "url": url,
            "target_price_paise": target_price_paise,
            "pincode": pincode or "",
            "variants": {v.external_variant_id: v for v in variants},
        }

        kb = build_variant_selection_keyboard(variants, target_price_paise)
        await status_msg.edit_text(
            f"🛒 <b>Multiple variants found!</b>\n\n"
            f"Please choose which flavor or size you want to track at <b>₹{target_price_paise//100}</b>:",
            reply_markup=kb,
            parse_mode="HTML",
        )

    except Exception as exc:
        await status_msg.edit_text(f"❌ <b>Failed to track product:</b>\n{exc}", parse_mode="HTML")


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list command."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    items = await tracker_service.list_user_subscriptions(update.effective_user.id)
    text = format_subscription_list(items)
    await update.effective_message.reply_html(text)


async def untrack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /untrack <listing_id> or /untrack_<listing_id>."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    raw_text = update.effective_message.text or ""

    listing_id = None
    if "_" in raw_text:
        # /untrack_42 format
        match = re.search(r"/untrack_(\d+)", raw_text)
        if match:
            listing_id = int(match.group(1))

    if not listing_id and context.args:
        try:
            listing_id = int(context.args[0])
        except ValueError:
            pass

    if not listing_id:
        await update.effective_message.reply_html(
            "⚠️ <b>Usage:</b> <code>/untrack &lt;listing_id&gt;</code>\n"
            "Find your listing ID via <code>/list</code>."
        )
        return

    success = await tracker_service.untrack_product(update.effective_user.id, listing_id)
    if success:
        await update.effective_message.reply_html(f"🗑️ Successfully removed listing <code>{listing_id}</code>.")
    else:
        await update.effective_message.reply_html(f"❌ Listing <code>{listing_id}</code> not found in your tracking list.")


async def pincode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pincode <pincode>."""
    if not update.effective_user or not update.effective_message:
        return

    args = context.args or []
    if not args or not _PINCODE_REGEX.match(args[0].strip()):
        await update.effective_message.reply_html(
            "⚠️ <b>Usage:</b> <code>/pincode &lt;6-digit pincode&gt;</code>\n"
            "<b>Example:</b> <code>/pincode 842002</code>"
        )
        return

    pincode = args[0].strip()
    tracker_service: TrackerService = context.bot_data["tracker_service"]
    await tracker_service.set_user_pincode(update.effective_user.id, pincode)
    await update.effective_message.reply_html(
        f"📍 <b>Default delivery pincode updated to:</b> <code>{pincode}</code>"
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not update.effective_message:
        return
    await update.effective_message.reply_html(
        "⚡ <b>PriceWatch 2.0 System Status</b>\n\n"
        "• <b>Status:</b> 🟢 Operational\n"
        "• <b>Check Frequency:</b> Every 15 minutes\n"
        "• <b>Engine:</b> Tiered HTTP & Scoped Extractors\n"
        "• <b>Amul Provider:</b> StoreHippo REST Handshake\n"
        "• <b>Database:</b> Coordinated PostgreSQL Lease Locks"
    )


async def amul_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /products or /amul command to browse and track Amul protein products."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )
    pincode = user.default_pincode or "842002"
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(pincode)

    text = format_amul_category_menu(pincode=pincode, substore=substore)
    kb = build_amul_category_keyboard()
    await update.effective_message.reply_html(text, reply_markup=kb)


async def history_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history <listing_id> or /history_<listing_id> to generate price trend chart."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    raw_text = update.effective_message.text or ""

    listing_id = None
    if "_" in raw_text:
        match = re.search(r"/history_(\d+)", raw_text)
        if match:
            listing_id = int(match.group(1))

    if not listing_id and context.args:
        try:
            listing_id = int(context.args[0])
        except ValueError:
            pass

    if not listing_id:
        subs = await tracker_service.list_user_subscriptions(update.effective_user.id)
        if not subs:
            await update.effective_message.reply_html(
                "📭 <b>You don't have any tracked products yet.</b>\n\n"
                "Paste any product link or type <code>/amul</code> to start tracking!"
            )
            return
        if len(subs) == 1:
            listing_id = subs[0][1].id
        else:
            lines = ["📊 <b>Select a product to view price chart:</b>\n"]
            for sub, l in subs:
                lines.append(f"• <b>{l.product_title}</b>: /history_{l.id}")
            await update.effective_message.reply_html("\n".join(lines))
            return

    listing = await tracker_service.get_listing(listing_id)
    if not listing:
        await update.effective_message.reply_html(f"❌ Listing <code>{listing_id}</code> not found.")
        return

    status_msg = await update.effective_message.reply_text("📈 Generating price chart...")

    observations = await tracker_service.get_price_history(listing_id, limit=50)
    subs = await tracker_service.list_user_subscriptions(update.effective_user.id)
    matching_sub = next((s[0] for s in subs if s[1].id == listing_id), None)
    target_paise = matching_sub.target_price_paise if matching_sub else None

    chart_bytes = ChartService.generate_price_history_chart(
        listing=listing,
        observations=observations,
        target_price_paise=target_paise,
    )

    if not chart_bytes:
        await status_msg.edit_text(
            f"⚠️ Insufficient price history data recorded yet for <b>{listing.product_title}</b>.\n"
            "Checks run automatically every 15 minutes!",
            parse_mode="HTML",
        )
        return

    await status_msg.delete()
    await update.effective_message.reply_photo(
        photo=chart_bytes,
        caption=(
            f"📊 <b>Price History: {listing.product_title}</b>\n"
            f"💰 <b>Current:</b> ₹{(listing.last_price_paise or 0)/100:,.0f} | "
            f"🎯 <b>Target:</b> ₹{(target_paise or 0)/100:,.0f}\n"
            f"🔗 <a href='{listing.canonical_url}'>Open Store Page</a>"
        ),
        parse_mode="HTML",
    )


async def plain_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle non-command plain text:
    1. If user is replying with a custom target price, set it.
    2. If message contains a URL, trigger stepwise product onboarding.
    """
    if not update.effective_user or not update.effective_message:
        return

    text = (update.effective_message.text or "").strip()
    tracker_service: TrackerService = context.bot_data["tracker_service"]

    # 1. Check if user is in custom price input state
    awaiting_listing_id = context.user_data.get("awaiting_custom_price")
    if awaiting_listing_id:
        paise = parse_inr_to_paise(text)
        if not paise or paise <= 0:
            await update.effective_message.reply_html(
                "❌ <b>Invalid price!</b> Please enter a valid number (e.g. <code>1200</code> or <code>₹1,200</code>)."
            )
            return

        context.user_data.pop("awaiting_custom_price", None)
        try:
            listing, sub = await tracker_service.create_subscription_for_listing(
                telegram_id=update.effective_user.id,
                listing_id=awaiting_listing_id,
                target_price_paise=paise,
            )
            conf_text = format_tracking_confirmation(listing, sub)
            kb = build_listing_card_keyboard(listing.id)
            await update.effective_message.reply_html(conf_text, reply_markup=kb)
            return
        except Exception as exc:
            await update.effective_message.reply_html(f"❌ Failed to set target price: {exc}")
            return

    # 2. Check if text contains a product URL
    url_match = re.search(r"https?://[^\s]+", text)
    if not url_match:
        return

    url = url_match.group(0)

    try:
        ProviderRegistry.get_provider_for_url(url)
    except Exception:
        # Not a supported store URL
        return

    status_msg = await update.effective_message.reply_text("🔍 Inspecting product URL...")

    try:
        # If Amul URL, route to Amul stock tracking immediately!
        if "shop.amul.com" in url or "amul.com" in url:
            user = await tracker_service.get_or_register_user(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
            )
            pincode = user.default_pincode or "110001"
            provider = AmulProvider()
            res = await provider.resolve_url(url, pincode=pincode)
            sku = res.pinned_variant_id or res.external_product_id
            quote = await provider.fetch_quote(url, sku, sku, pincode=pincode)

            listing = CanonicalListing(
                provider_code="amul",
                provider_tier=1,
                external_product_id=sku,
                external_variant_id=sku,
                pincode=pincode,
                canonical_url=url,
                product_title=quote.raw_variant_title or res.product_title,
                variant_title="Standard Pack",
                currency="INR",
                last_price_paise=quote.price_paise,
                last_mrp_paise=quote.mrp_paise,
                last_available=quote.available,
                inventory_quantity=quote.inventory_quantity,
                is_monitored=True,
            )
            saved_listing = await tracker_service.listing_repo.get_or_create_listing(listing)
            is_in_stock = quote.available and (quote.inventory_quantity is None or quote.inventory_quantity > 0)
            saved_sub = await tracker_service.sub_repo.create_or_update_subscription(
                Subscription(
                    telegram_id=update.effective_user.id,
                    listing_id=saved_listing.id,
                    target_price_paise=quote.price_paise or 0,
                    notify_on_restock=True,
                    is_active=True,
                    alert_rearmed=not is_in_stock,
                    last_alerted_price_paise=quote.price_paise if is_in_stock else None,
                )
            )
            conf_text = format_amul_tracking_confirmed(
                saved_listing.product_title,
                sku,
                pincode,
                quote.available,
                quote.inventory_quantity or 0,
            )
            await status_msg.edit_text(conf_text, parse_mode="HTML")
            return

        # For Amazon, Nakpro, MuscleBlaze, etc.: Stepwise onboarding!
        listing = await tracker_service.resolve_and_preview_url(
            telegram_id=update.effective_user.id,
            url=url,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

        # Save pending custom price target for convenience
        context.user_data["awaiting_custom_price"] = listing.id

        preview_text = format_stepwise_product_preview(listing)
        kb = build_target_price_keyboard(
            listing_id=listing.id,
            current_price_paise=listing.last_price_paise or 0,
        )
        await status_msg.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")

    except VariantAmbiguousError as amb_err:
        variants = amb_err.variants
        context.user_data["pending_track_variants"] = {
            "url": url,
            "variants": {v.external_variant_id: v for v in variants},
        }
        kb = build_variant_selection_keyboard(variants, 0)
        await status_msg.edit_text(
            "🛒 <b>Multiple variants found!</b>\n\n"
            "Please choose which flavor or size you want to track:",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as exc:
        await status_msg.edit_text(f"❌ <b>Failed to inspect link:</b>\n{exc}", parse_mode="HTML")
