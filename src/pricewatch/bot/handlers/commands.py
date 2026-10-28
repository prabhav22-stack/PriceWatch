"""Telegram command handlers (/start, /help, /track, /list, /untrack, /pincode, /status, /amul, /history)."""

import re
from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_amul_analytics,
    format_amul_category_menu,
    format_amul_favourites_messages,
    format_amul_product_count,
    format_amul_search_messages,
    format_amul_tracking_confirmed,
    format_auto_order_overview,
    format_help_message,
    format_settings_menu,
    format_stepwise_product_preview,
    format_subscription_list,
    format_tracking_confirmation,
    format_welcome_message,
)
from pricewatch.bot.keyboards import (
    build_amul_category_keyboard,
    build_listing_card_keyboard,
    build_settings_keyboard,
    build_target_price_keyboard,
    build_variant_selection_keyboard,
)
from pricewatch.domain.exceptions import VariantAmbiguousError
from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.providers.amul import AmulProvider
from pricewatch.providers.base import ProviderRegistry
from pricewatch.services.amul_auto_order import AmulAutoOrderService
from pricewatch.services.amul_stock_tracker import AmulStockTracker
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

    # Check for deeplink payload: e.g. /start track_WPCCP01_01, /start fav_WPCCP01_01, /start ao_WPCCP01_01
    if context.args:
        payload = context.args[0].strip()

        # Delete the incoming /start <payload> message immediately so it vanishes from chat
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        if payload.startswith("fav_"):
            sku = payload.replace("fav_", "")
            prod_name = sku
            try:
                pincode = db_user.default_pincode or "842002"
                provider = AmulProvider()
                cat_items = await provider.fetch_category_products(category_id="protein", pincode=pincode, limit=100)
                m = next((it for it in cat_items if it.get("sku") == sku), None)
                if m and m.get("name"):
                    prod_name = m["name"]
            except Exception:
                pass

            added = await tracker_service.toggle_user_favourite(user.id, sku)
            if added:
                await update.effective_chat.send_message(
                    f"⭐ <b>Added to favourites:</b> {prod_name}\n\n"
                    "View all your starred products anytime with <code>/favourites</code>.",
                    parse_mode="HTML",
                )
            else:
                await update.effective_chat.send_message(
                    f"🗑️ <b>Removed from favourites:</b> {prod_name}",
                    parse_mode="HTML",
                )
            return

        if payload.startswith("ao_") or payload.startswith("addautoorder_") or payload.startswith("removeautoorder_"):
            await update.effective_chat.send_message(
                "⚡ Amul automated checkout is currently disabled. Use <code>/trackall</code> for instant restock alerts!",
                parse_mode="HTML",
            )
            return

        if payload.startswith("track_"):
            sku = payload.replace("track_", "")
            user_subs = await tracker_service.list_user_subscriptions(user.id)
            match = next((s for s in user_subs if s[1].provider_code == "amul" and s[1].external_variant_id == sku), None)

            pincode = db_user.default_pincode or "842002"
            provider = AmulProvider()
            quote = await provider.fetch_quote("", sku, sku, pincode=pincode)

            prod_alias = sku
            product_title = quote.raw_variant_title or sku
            try:
                cat_items = await provider.fetch_category_products(category_id="protein", pincode=pincode, limit=100)
                m = next((it for it in cat_items if it.get("sku") == sku), None)
                if m:
                    if m.get("alias"):
                        prod_alias = m["alias"].replace(" ", "")
                    if m.get("name"):
                        product_title = m["name"]
            except Exception:
                pass

            if match:
                await update.effective_chat.send_message(
                    f"✅ You are already tracking the product: <b>{product_title}</b>",
                    parse_mode="HTML",
                )
                return

            listing = CanonicalListing(
                provider_code="amul",
                provider_tier=1,
                external_product_id=sku,
                external_variant_id=sku,
                pincode=pincode,
                canonical_url=f"https://shop.amul.com/en/product/{prod_alias}",
                product_title=product_title,
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
            await update.effective_chat.send_message(
                f"🔍 <b>Tracking product: {product_title}</b>\n"
                f"You will receive updates when the product is available.",
                parse_mode="HTML",
            )
            return

        if payload.startswith("untrack_"):
            sku = payload.replace("untrack_", "")
            subs = await tracker_service.list_user_subscriptions(user.id)
            match = next((s for s in subs if s[1].provider_code == "amul" and s[1].external_variant_id == sku), None)

            prod_name = sku
            if match:
                prod_name = match[1].product_title
                await tracker_service.untrack_product(user.id, match[1].id)
                await update.effective_chat.send_message(
                    f"🔍 <b>Untracking product: {prod_name}</b>\n"
                    f"You will no longer receive updates for this product.",
                    parse_mode="HTML",
                )
            else:
                pincode = db_user.default_pincode or "842002"
                provider = AmulProvider()
                try:
                    cat_items = await provider.fetch_category_products(category_id="protein", pincode=pincode, limit=100)
                    m = next((it for it in cat_items if it.get("sku") == sku), None)
                    if m and m.get("name"):
                        prod_name = m["name"]
                except Exception:
                    pass
                await update.effective_chat.send_message(
                    f"❌ You are not tracking the product: <b>{prod_name}</b>",
                    parse_mode="HTML",
                )
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

    args = context.args if isinstance(context.args, list) else []
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
        subs = await tracker_service.list_user_subscriptions(update.effective_user.id)
        if not subs:
            await update.effective_message.reply_html(
                "📭 <b>You have no active tracked products to untrack.</b>\n\n"
                "Browse products with <code>/products</code> or paste any product link to start tracking."
            )
            return
        lines = [
            "🗑️ <b>Select a product to stop tracking:</b>\n"
        ]
        for sub, listing in subs:
            lines.append(f"• <b>{listing.product_title}</b>: /untrack_{listing.id}")
        lines.append("\nTap any link above to untrack immediately.")
        await update.effective_message.reply_html("\n".join(lines))
        return

    # Delete the incoming /untrack_<id> command message so it vanishes from chat!
    if "_" in raw_text:
        try:
            await update.effective_message.delete()
        except Exception:
            pass

    listing = await tracker_service.get_listing(listing_id)
    listing_name = listing.product_title if listing else f"Listing #{listing_id}"

    success = await tracker_service.untrack_product(update.effective_user.id, listing_id)
    if success:
        await update.effective_chat.send_message(
            f"🔍 <b>Untracking product: {listing_name}</b>\n"
            f"You will no longer receive updates for this product.",
            parse_mode="HTML",
        )
    else:
        await update.effective_chat.send_message(
            f"❌ Product <b>{listing_name}</b> not found in your tracking list.",
            parse_mode="HTML",
        )


async def pincode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pincode command (views current pincode, or updates if 6-digit argument provided)."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
    args = context.args if isinstance(context.args, list) else []

    if args and _PINCODE_REGEX.match(args[0].strip()):
        new_pin = args[0].strip()
        await tracker_service.set_user_pincode(update.effective_user.id, new_pin)
        amul_provider = AmulProvider()
        substore = await amul_provider.resolve_substore_for_pincode(new_pin)
        await update.effective_message.reply_html(
            f"📍 <b>Default delivery pincode updated to:</b> <code>{new_pin}</code> (Warehouse: <i>{substore}</i>)"
        )
        return

    curr_pin = user.default_pincode or "842002"
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(curr_pin)
    await update.effective_message.reply_html(
        f"📍 Your current pincode is: <b>{curr_pin} ({substore})</b>\n\n"
        "To change your pincode, use the command <b>/setpincode</b> followed by your new pincode.\n"
        "Example: <code>/setpincode 842002</code>"
    )


async def setpincode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setpincode <6-digit pincode>."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    args = context.args if isinstance(context.args, list) else []
    if not args or not _PINCODE_REGEX.match(args[0].strip()):
        user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
        curr_pin = user.default_pincode or "842002"
        amul_provider = AmulProvider()
        substore = await amul_provider.resolve_substore_for_pincode(curr_pin)
        await update.effective_message.reply_html(
            f"📍 <b>Current Delivery Pincode:</b> <code>{curr_pin}</code> (Warehouse: <i>{substore}</i>)\n\n"
            "To set a new pincode, send: <code>/setpincode &lt;6-digit pincode&gt;</code>\n"
            "<b>Example:</b> <code>/setpincode 842002</code>"
        )
        return

    new_pin = args[0].strip()
    await tracker_service.set_user_pincode(update.effective_user.id, new_pin)
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(new_pin)
    await update.effective_message.reply_html(
        f"📍 <b>Default delivery pincode updated to:</b> <code>{new_pin}</code> (Warehouse: <i>{substore}</i>)"
    )


async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /support command."""
    if not update.effective_message:
        return
    text = (
        "🤝 <b>PriceWatch Support & Community</b>\n\n"
        "PriceWatch is open-source and built for real-time price & stock tracking.\n\n"
        "• <b>GitHub:</b> <a href=\"https://github.com/prabhav22-stack/PriceWatch\">prabhav22-stack/PriceWatch</a>\n"
        "• <b>Commands Help:</b> Type <code>/help</code> for full usage guide\n"
        "• <b>Status & Uptime:</b> Type <code>/status</code> for health metrics\n\n"
        "Have feedback, feature requests, or encountered an issue? Let us know!"
    )
    await update.effective_message.reply_html(text, disable_web_page_preview=True)


async def map_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /map command."""
    if not update.effective_message:
        return
    text = (
        "🗺️ <b>Amul Regional Warehouse & Delivery Hubs</b>\n\n"
        "Amul Shop routes orders based on regional cold storage hubs:\n"
        "• <b>Bihar Hub (bihar):</b> Serving Pincodes <code>842xxx</code>, <code>800xxx</code> (Patna/Muzaffarpur)\n"
        "• <b>Delhi NCR (delhi):</b> Serving Pincodes <code>110xxx</code>, <code>201xxx</code>, <code>122xxx</code>\n"
        "• <b>Mumbai Hub (mumbai):</b> Serving Pincodes <code>400xxx</code>\n"
        "• <b>Gujarat Hub (gujarat):</b> Serving Pincodes <code>380xxx</code>, <code>388xxx</code> (Anand/Ahmedabad)\n"
        "• <b>Bangalore Hub (bangalore):</b> Serving Pincodes <code>560xxx</code>\n\n"
        "Use <code>/setpincode &lt;pincode&gt;</code> to automatically connect to your regional warehouse."
    )
    await update.effective_message.reply_html(text)


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

    if isinstance(context.args, list) and len(context.args) > 0:
        await search_command_handler(update, context)
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


async def search_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <query> across Amul products."""
    if not update.effective_user or not update.effective_message:
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.effective_message.reply_html(
            "🔍 <b>Usage:</b> <code>/search &lt;keyword&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/search blueberry</code>\n"
            "• <code>/search lassi</code>\n"
            "• <code>/search whey</code>"
        )
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )
    pincode = user.default_pincode or "842002"

    wait_msg = await update.effective_message.reply_text(f"🔍 Searching Amul for \"{query}\"...")

    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(pincode)
    products = await amul_provider.search_products(query, pincode=pincode)

    stock_tracker = AmulStockTracker.get_instance()
    await stock_tracker.load_history_for_substore(substore)
    stock_tracker.record_batch_observations(products, substore=substore)
    stock_histories = {
        p.get("sku"): stock_tracker.get_history(p.get("sku", ""), substore)
        for p in products
        if p.get("sku")
    }

    user_subs = await tracker_service.list_user_subscriptions(user.telegram_id)
    tracked_skus = {s[1].external_variant_id for s in user_subs if s[1].provider_code == "amul"}
    fav_skus = set(user.favourite_skus or [])
    ao_skus = set(user.auto_order_skus or [])
    bot_username = context.bot.username or "wheypricewatch_bot"

    messages = format_amul_search_messages(
        query=query,
        pincode=pincode,
        substore=substore,
        products=products,
        tracked_skus=tracked_skus,
        favourite_skus=fav_skus,
        auto_order_skus=ao_skus,
        bot_username=bot_username,
        stock_histories=stock_histories,
    )

    await wait_msg.delete()
    for chunk in messages:
        await update.effective_message.reply_html(chunk, disable_web_page_preview=True)


async def favourites_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /favourites command to list user's starred products."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )
    fav_skus = set(user.favourite_skus or [])
    pincode = user.default_pincode or "842002"

    if not fav_skus:
        await update.effective_message.reply_html(
            "⭐ <b>You have no favourites yet.</b>\n\n"
            "Browse products with <code>/amul</code> or search with <code>/search</code> and tap <b>[Favourite]</b> on any item to save it here!"
        )
        return

    wait_msg = await update.effective_message.reply_text("⭐ Fetching your favourite products...")
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(pincode)

    # Fetch protein & dairy products to resolve favourite items
    all_prods = await amul_provider.fetch_category_products("protein", pincode=pincode, limit=100)
    fav_products = [p for p in all_prods if p.get("sku") in fav_skus]

    stock_tracker = AmulStockTracker.get_instance()
    await stock_tracker.load_history_for_substore(substore)
    stock_tracker.record_batch_observations(fav_products, substore=substore)
    stock_histories = {
        p.get("sku"): stock_tracker.get_history(p.get("sku", ""), substore)
        for p in fav_products
        if p.get("sku")
    }

    user_subs = await tracker_service.list_user_subscriptions(user.telegram_id)
    tracked_skus = {s[1].external_variant_id for s in user_subs if s[1].provider_code == "amul"}
    ao_skus = set(user.auto_order_skus or [])
    bot_username = context.bot.username or "wheypricewatch_bot"

    messages = format_amul_favourites_messages(
        pincode=pincode,
        substore=substore,
        products=fav_products,
        tracked_skus=tracked_skus,
        favourite_skus=fav_skus,
        auto_order_skus=ao_skus,
        bot_username=bot_username,
        stock_histories=stock_histories,
    )

    await wait_msg.delete()
    for chunk in messages:
        await update.effective_message.reply_html(chunk, disable_web_page_preview=True)


async def analytics_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analytics command."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
    pincode = user.default_pincode or "842002"

    wait_msg = await update.effective_message.reply_text("📊 Generating warehouse analytics...")
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(pincode)
    products = await amul_provider.fetch_category_products("protein", pincode=pincode, limit=100)

    user_subs = await tracker_service.list_user_subscriptions(user.telegram_id)
    tracked_count = sum(1 for s in user_subs if s[1].provider_code == "amul")

    text = format_amul_analytics(
        substore=substore,
        pincode=pincode,
        products=products,
        user_tracked_count=tracked_count,
    )
    await wait_msg.delete()
    await update.effective_message.reply_html(text)


async def productcount_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /productcount and /count commands."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
    pincode = user.default_pincode or "842002"

    wait_msg = await update.effective_message.reply_text("📦 Fetching stock count tables...")
    amul_provider = AmulProvider()
    products = await amul_provider.fetch_category_products("protein", pincode=pincode, limit=100)

    text = format_amul_product_count(products)
    await wait_msg.delete()
    await update.effective_message.reply_html(text)


async def settings_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)

    text = format_settings_menu(user)
    kb = build_settings_keyboard(user)
    await update.effective_message.reply_html(text, reply_markup=kb)


async def autoorder_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /autoorder command."""
    if not update.effective_user or not update.effective_message:
        return

    text = (
        "⚡ <b>Amul Auto-Ordering Notice</b>\n\n"
        "Direct automated checkout on Amul Shop requires dedicated merchant credentials and is currently disabled to prevent failed transactions.\n\n"
        "<b>Recommended Setup for Instant Purchase:</b>\n"
        "• Turn on <b>All-Protein Alerts</b> with <code>/trackall</code> (or in <code>/settings</code>).\n"
        "• Set repeated alerts with <code>/repeat 0</code> so you get alerted continuously while in stock.\n"
        "• Restock alerts include direct instant checkout links to purchase before stock runs out!"
    )
    await update.effective_message.reply_html(text)


async def trackall_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle automated restock alerts for all Amul protein items."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
    favs = list(user.favourite_skus or [])

    if "ALL_PROTEIN" in favs:
        favs.remove("ALL_PROTEIN")
        await tracker_service.update_user_settings(user.telegram_id, favourite_skus=favs)
        await update.effective_message.reply_html(
            "🔕 <b>All-Protein Restock Alerts: DISABLED</b>\n\n"
            "You will now only receive restock notifications for items specifically in your "
            "<code>/tracked</code> list or <code>/favourites</code>."
        )
    else:
        favs.append("ALL_PROTEIN")
        await tracker_service.update_user_settings(user.telegram_id, favourite_skus=favs)
        pincode = user.default_pincode or "842002"
        await update.effective_message.reply_html(
            "🔔 <b>All-Protein Restock Alerts: ACTIVATED!</b>\n\n"
            f"You will now receive instant restock alerts whenever <b>ANY</b> Amul protein product "
            f"(Whey, Buttermilk, Lassi, Milkshakes, Paneer) comes into stock for delivery pincode <code>{pincode}</code>!\n\n"
            "• Type <code>/trackall</code> again anytime to turn it off.\n"
            "• Configure notifications or auto-order with <code>/settings</code>."
        )


async def repeat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /repeat <count> to configure dynamic decreasing stock updates."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = await tracker_service.get_or_register_user(telegram_id=update.effective_user.id)
    args = context.args if isinstance(context.args, list) else []

    if not args:
        cur_str = "♾️ Until Stock Runs Out" if user.max_notify_count == 0 else f"{user.max_notify_count} dynamic alerts"
        await update.effective_message.reply_html(
            "🔁 <b>Repeated Stock Alerts Configuration</b>\n\n"
            f"• Current setting: <b>{cur_str}</b>\n\n"
            "<b>Usage:</b>\n"
            "• <code>/repeat 1</code> to <code>/repeat 10</code> - Receive up to N dynamic updates as stock decreases.\n"
            "• <code>/repeat 0</code> or <code>/repeat oos</code> - Continuous updates every time stock drops until sold out.\n\n"
            "💡 You can also use the interactive buttons in <code>/settings</code>."
        )
        return

    arg = args[0].strip().lower()
    if arg in ("0", "oos", "continuous", "infinite", "unlimited"):
        await tracker_service.update_user_settings(user.telegram_id, max_notify_count=0)
        await update.effective_message.reply_html(
            "✅ <b>Repeat alerts set to: ♾️ Until Stock Runs Out!</b>\n\n"
            "You will now receive dynamic restock notifications whenever available warehouse units decrease "
            "until the item completely runs out of stock."
        )
        return

    try:
        count = int(arg)
        if count < 1 or count > 100:
            await update.effective_message.reply_html("⚠️ Please enter a number between 1 and 10 (or 0 for continuous until OOS).")
            return
        await tracker_service.update_user_settings(user.telegram_id, max_notify_count=count)
        await update.effective_message.reply_html(
            f"✅ <b>Repeat alerts set to: {count} dynamic alerts per drop!</b>\n\n"
            f"You will receive up to {count} updates whenever available warehouse stock decreases."
        )
    except ValueError:
        await update.effective_message.reply_html("⚠️ Invalid number. Use e.g. <code>/repeat 3</code> or <code>/repeat oos</code>.")


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
