"""Telegram command handlers (/start, /help, /track, /list, /untrack, /pincode, /status, /amul, /history)."""

import html
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_amul_analytics,
    format_amul_category_menu,
    format_amul_favourites_messages,
    format_amul_product_count,
    format_amul_search_messages,
    format_amul_tracking_confirmed,
    format_auto_order_overview,
    format_comparison_report,
    format_cross_store_alert,
    format_help_message,
    format_instock_report,
    format_settings_menu,
    format_stepwise_product_preview,
    format_subscription_list,
    format_tracking_confirmation,
    format_welcome_message,
)
from pricewatch.bot.keyboards import (
    build_action_nav_keyboard,
    build_amul_category_keyboard,
    build_category_navigation_keyboard,
    build_comparison_keyboard,
    build_cross_store_alert_keyboard,
    build_instock_keyboard,
    build_listing_card_keyboard,
    build_pincode_keyboard,
    build_repeat_keyboard,
    build_search_suggestions_keyboard,
    build_settings_keyboard,
    build_target_price_keyboard,
    build_tracking_mode_keyboard,
    build_variant_selection_keyboard,
    build_welcome_keyboard,
)
from pricewatch.config import settings
from pricewatch.domain.exceptions import VariantAmbiguousError
from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.logging_setup import get_logger

logger = get_logger("commands")
from pricewatch.providers.amul import AmulProvider
from pricewatch.providers.base import ProviderRegistry
from pricewatch.services.amul_auto_order import AmulAutoOrderService
from pricewatch.services.amul_stock_tracker import AmulStockTracker
from pricewatch.services.chart_service import ChartService
from pricewatch.services.check_orchestrator import CheckOrchestrator
from pricewatch.services.discovery_service import DiscoveryService
from pricewatch.services.multi_channel_notifier import notifier as multichannel_notifier
from pricewatch.services.vision_extractor import vision_extractor
from pricewatch.services.tracker_service import TrackerService
from pricewatch.utils.time_utils import format_ist_datetime
from pricewatch.validation.normalizer import format_paise_to_inr, parse_inr_to_paise


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
            kb = build_action_nav_keyboard("⭐ View Favourites", "nav:favs", "🥛 Browse More", "amul_menu")
            if added:
                await update.effective_chat.send_message(
                    f"⭐ <b>Added to favourites:</b> {prod_name}\n\n"
                    "View all your starred products anytime with <code>/favourites</code>.",
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            else:
                await update.effective_chat.send_message(
                    f"🗑️ <b>Removed from favourites:</b> {prod_name}",
                    reply_markup=kb,
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
                kb = build_action_nav_keyboard("📋 View Tracked", "nav:tracked", "🥛 Browse More", "amul_menu")
                await update.effective_chat.send_message(
                    f"✅ You are already tracking the product: <b>{product_title}</b>",
                    reply_markup=kb,
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
            kb = build_action_nav_keyboard("📋 View Tracked Products", "nav:tracked", "🥛 Browse More", "amul_menu")
            await update.effective_chat.send_message(
                f"🔍 <b>Tracking product: {product_title}</b>\n"
                f"You will receive updates when the product is available.",
                reply_markup=kb,
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
                kb = build_action_nav_keyboard("📋 View Tracked Products", "nav:tracked", "🥛 Browse Products", "amul_menu")
                await update.effective_chat.send_message(
                    f"🔍 <b>Untracking product: {prod_name}</b>\n"
                    f"You will no longer receive updates for this product.",
                    reply_markup=kb,
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
                kb = build_action_nav_keyboard("📋 View Tracked", "nav:tracked", "🥛 Browse Products", "amul_menu")
                await update.effective_chat.send_message(
                    f"❌ You are not tracking the product: <b>{prod_name}</b>",
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            return

    text = format_welcome_message(user.first_name or "there")
    await update.effective_message.reply_html(text, reply_markup=build_welcome_keyboard())


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.effective_message:
        return
    text = format_help_message()
    kb = build_action_nav_keyboard("🥛 Browse Amul", "amul_menu", "📋 Tracked Items", "nav:tracked")
    await update.effective_message.reply_html(text, reply_markup=kb)


async def track_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /track [url] [target_price] [pincode] or interactive conversational onboarding."""
    if not update.effective_user or not update.effective_message:
        return

    args = context.args if isinstance(context.args, list) else []

    # 1. If user sent just /track with no arguments: ask them for the product URL
    if len(args) == 0:
        context.user_data["awaiting_track_url"] = True
        prompt_text = (
            "🔗 <b>Send Product Link to Track</b>\n\n"
            "Please paste or send the URL of the product you want to track:\n\n"
            "• 🌿 <b>Nutrabay:</b> Shilajit, Whey Protein, Creatine, Vitamins\n"
            "• 📦 <b>Amazon & Amazon Fresh:</b> Groceries & Supplements\n"
            "• 🥛 <b>Amul Shop:</b> Whey Protein, Paneer, Butter, Ghee\n"
            "• 🛍️ <b>Shopify Stores:</b> Nakpro, MuscleBlaze, The Whole Truth, etc.\n\n"
            "<i>💡 After sending the link, you can choose to track when it's back in stock, track significant discounts, or set a target price!</i>"
        )
        cancel_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
            ]
        ])
        await update.effective_message.reply_html(prompt_text, reply_markup=cancel_kb)
        return

    # 2. If user sent /track <url> with only the URL: directly inspect and show tracking mode options!
    if len(args) == 1:
        url = args[0].strip()
        await _inspect_url_and_prompt_modes(update, context, url)
        return

    # 3. Direct power-user shortcut: /track <url> <target_price> [pincode]
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
        if listing.last_available is False:
            import asyncio
            asyncio.create_task(
                notify_if_available_elsewhere(
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                    listing=listing,
                    context=context,
                )
            )

    except VariantAmbiguousError as amb_err:
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


async def compare_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /compare [url or product name] to find where it is in stock and at the lowest price."""
    if not update.effective_user or not update.effective_message:
        return

    discovery_service: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
    args = context.args if isinstance(context.args, list) else []

    if not args:
        context.user_data["awaiting_compare_query"] = True
        kb = build_action_nav_keyboard("❌ Cancel", "trk:cancel", "🏠 Main Menu", "nav:home", include_home=False)
        await update.effective_message.reply_html(
            "🔍 <b>Find Best Price Across Stores</b>\n\n"
            "Please send the product name or store link you want to compare.\n\n"
            "<b>Examples:</b>\n"
            "• <code>Nutrabay Pure Shilajit 20g</code>\n"
            "• <code>Nakpro Perform Whey 1kg</code>\n"
            "• Or paste any product link (Nutrabay, Amazon, HyugaLife, etc.)",
            reply_markup=kb,
        )
        return

    query_str = " ".join(args).strip()
    status_msg = await update.effective_message.reply_html(
        f"🔍 <i>Searching across trusted stores for best price and stock:</i>\n<b>{html.escape(query_str)}</b>..."
    )

    try:
        from pricewatch.services.gemini_service import gemini_service
        effective_query = query_str
        if not query_str.startswith("http") and gemini_service.is_available:
            try:
                norm = await gemini_service.normalize_user_query(query_str)
                if norm and norm.get("clean_query"):
                    effective_query = norm["clean_query"]
            except Exception:
                pass

        result = await discovery_service.compare_query(effective_query)
        report_text = format_comparison_report(result)
        kb = build_comparison_keyboard(result)
        await status_msg.edit_text(
            report_text,
            reply_markup=kb,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as exc:
        safe_exc = html.escape(str(exc))
        await status_msg.edit_text(
            f"❌ <b>Price comparison error:</b>\n{safe_exc}\n\nPlease try again with a simpler product name or direct link.",
            parse_mode="HTML",
        )


async def instock_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /instock <product name or tracked id> to instantly search where a product is in stock."""
    if not update.effective_user or not update.effective_message:
        return

    discovery_service: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
    tracker_service: Optional[TrackerService] = context.bot_data.get("tracker_service")
    args = context.args if isinstance(context.args, list) else []

    # Check if invoked via shorthand /instock_<id> or /instock <id>
    raw_text = (
        update.effective_message.text
        if isinstance(getattr(update.effective_message, "text", None), str)
        else ""
    )
    m_id = re.search(r"^/instock_(\d+)", raw_text) if raw_text else None
    listing_id = int(m_id.group(1)) if m_id else (int(args[0]) if len(args) == 1 and args[0].isdigit() else None)

    if listing_id and tracker_service:
        listing = await tracker_service.get_listing(listing_id)
        if listing:
            title_display = html.escape(listing.product_title)
            status_msg = await update.effective_message.reply_html(
                f"⚡ <i>Checking real-time stock across all stores for tracked product:</i>\n<b>{title_display}</b>..."
            )
            try:
                result = await discovery_service.compare_listing(listing)
                report_text = format_instock_report(result)
                kb = build_instock_keyboard(result)
                await status_msg.edit_text(
                    report_text,
                    reply_markup=kb,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                return
            except Exception as exc:
                safe_exc = html.escape(str(exc))
                await status_msg.edit_text(f"❌ <b>Stock check error:</b>\n{safe_exc}", parse_mode="HTML")
                return

    if not args:
        context.user_data["awaiting_instock_query"] = True
        kb = build_action_nav_keyboard("❌ Cancel", "trk:cancel", "🏠 Main Menu", "nav:home", include_home=False)
        await update.effective_message.reply_html(
            "⚡ <b>Instant Stock Finder</b>\n\n"
            "Please send the product name you want to check live stock for.\n\n"
            "<b>Examples:</b>\n"
            "• <code>Nutrabay Shilajit</code>\n"
            "• <code>Amul Whey Protein</code>\n"
            "• <code>Nakpro Malai Kulfi Whey</code>\n"
            "• <code>MuscleBlaze Biozyme Gold 1kg</code>",
            reply_markup=kb,
        )
        return

    query_str = " ".join(args).strip()
    status_msg = await update.effective_message.reply_html(
        f"⚡ <i>Checking real-time stock across stores for:</i>\n<b>{html.escape(query_str)}</b>..."
    )

    try:
        from pricewatch.services.gemini_service import gemini_service
        effective_query = query_str
        if not query_str.startswith("http") and gemini_service.is_available:
            try:
                norm = await gemini_service.normalize_user_query(query_str)
                if norm and norm.get("clean_query"):
                    effective_query = norm["clean_query"]
            except Exception:
                pass

        result = await discovery_service.compare_query(effective_query)
        report_text = format_instock_report(result)
        kb = build_instock_keyboard(result)
        await status_msg.edit_text(
            report_text,
            reply_markup=kb,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as exc:
        safe_exc = html.escape(str(exc))
        await status_msg.edit_text(
            f"❌ <b>Stock check error:</b>\n{safe_exc}\n\nPlease try again with a simpler product name.",
            parse_mode="HTML",
        )


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list or /tracked command."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    items = await tracker_service.list_user_subscriptions(update.effective_user.id)
    text = format_subscription_list(items)
    kb = (
        build_action_nav_keyboard("🥛 Browse Products", "amul_menu", "⭐ Favourites", "nav:favs")
        if not items
        else build_action_nav_keyboard("🥛 Add More Products", "amul_menu", "⚙️ Alert Settings", "cfg:refresh")
    )
    await update.effective_message.reply_html(text, reply_markup=kb)


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
                "Browse products with <code>/products</code> or paste any product link to start tracking.",
                reply_markup=build_action_nav_keyboard("🥛 Browse Products", "amul_menu", "🏠 Main Menu", "nav:home", include_home=False),
            )
            return
        lines = [
            "🗑️ <b>Select a product to stop tracking:</b>\n"
        ]
        buttons: List[List[InlineKeyboardButton]] = []
        for sub, listing in subs:
            trunc = (listing.product_title[:28] + "..") if len(listing.product_title) > 28 else listing.product_title
            lines.append(f"• <b>{html.escape(listing.product_title)}</b>: /untrack_{listing.id}")
            buttons.append([InlineKeyboardButton(f"🗑️ Untrack: {trunc}", callback_data=f"del:confirm:{listing.id}")])
        buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home")])
        lines.append("\nTap any product button below or command link above to untrack:")
        await update.effective_message.reply_html("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))
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
        kb = build_action_nav_keyboard("📋 View Tracked List", "nav:tracked", "🥛 Browse Amul", "amul_menu")
        await update.effective_chat.send_message(
            f"🔍 <b>Untracking product: {html.escape(listing_name)}</b>\n"
            f"You will no longer receive updates for this product.",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await update.effective_chat.send_message(
            f"❌ Product <b>{html.escape(listing_name)}</b> not found in your tracking list.",
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
        kb = build_pincode_keyboard(new_pin)
        await update.effective_message.reply_html(
            f"📍 <b>Default delivery pincode updated to:</b> <code>{new_pin}</code> (Warehouse: <i>{substore}</i>)",
            reply_markup=kb,
        )
        return

    curr_pin = user.default_pincode or "842002"
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(curr_pin)
    kb = build_pincode_keyboard(curr_pin)
    await update.effective_message.reply_html(
        f"📍 Your current pincode is: <b>{curr_pin} ({substore})</b>\n\n"
        "Tap a quick warehouse hub below or send <code>/setpincode &lt;6-digit&gt;</code>:\n"
        "Example: <code>/setpincode 842002</code>",
        reply_markup=kb,
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
        kb = build_pincode_keyboard(curr_pin)
        await update.effective_message.reply_html(
            f"📍 <b>Current Delivery Pincode:</b> <code>{curr_pin}</code> (Warehouse: <i>{substore}</i>)\n\n"
            "Tap a quick warehouse hub below or send <code>/setpincode &lt;6-digit pincode&gt;</code>:\n"
            "<b>Example:</b> <code>/setpincode 842002</code>",
            reply_markup=kb,
        )
        return

    new_pin = args[0].strip()
    await tracker_service.set_user_pincode(update.effective_user.id, new_pin)
    amul_provider = AmulProvider()
    substore = await amul_provider.resolve_substore_for_pincode(new_pin)
    kb = build_pincode_keyboard(new_pin)
    await update.effective_message.reply_html(
        f"📍 <b>Default delivery pincode updated to:</b> <code>{new_pin}</code> (Warehouse: <i>{substore}</i>)",
        reply_markup=kb,
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
    kb = build_action_nav_keyboard("🥛 Browse Amul", "amul_menu", "📍 Change Pincode", "nav:pincode")
    await update.effective_message.reply_html(text, reply_markup=kb)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command with accurate tiered frequency metrics."""
    if not update.effective_message:
        return
    text = (
        "⚡ <b>PriceWatch 2.0 System Status</b>\n\n"
        "• <b>Status:</b> 🟢 Operational\n"
        "• <b>Tiered Check Frequencies:</b>\n"
        f"   🥛 <b>Amul Shop:</b> Every {settings.AMUL_CHECK_INTERVAL_SECONDS}s (High-frequency REST poller)\n"
        f"   🛍️ <b>Shopify Stores (Nakpro, etc.):</b> Every {settings.SHOPIFY_CHECK_INTERVAL_MINUTES} minutes\n"
        f"   🛒 <b>Marketplaces (Amazon, Fresh):</b> Every {settings.MARKETPLACE_CHECK_INTERVAL_MINUTES} minutes\n"
        "• <b>Engine:</b> Tiered HTTP & Scoped Extractors\n"
        "• <b>Amul Provider:</b> StoreHippo REST Handshake\n"
        "• <b>Database:</b> Coordinated PostgreSQL Lease Locks\n\n"
        "💡 <i>Tip: Send <code>/check</code> anytime for an instant live check of your tracked items!</i>"
    )
    kb = build_action_nav_keyboard("⚡ Run Live /check", "nav:live_check", "📋 Tracked Items", "nav:tracked")
    await update.effective_message.reply_html(text, reply_markup=kb)


async def check_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Instant live on-demand check for all user tracked items."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user_id = update.effective_user.id
    subs = await tracker_service.list_user_subscriptions(user_id)

    if not subs:
        kb = build_action_nav_keyboard("🥛 Browse Products", "amul_menu", "⭐ Favourites", "nav:favs")
        await update.effective_message.reply_html(
            "📭 <b>You have no active tracked items to check.</b>\n\n"
            "Browse products with <code>/products</code> or paste any product link here to start tracking!",
            reply_markup=kb,
        )
        return

    status_msg = await update.effective_message.reply_html(
        f"⏳ <i>Performing instant live check across your <b>{len(subs)}</b> tracked items...</i>"
    )

    orchestrator = CheckOrchestrator(max_concurrency=3)
    results_lines = [
        f"⚡ <b>Live Stock & Price Check</b> ({len(subs)} items)\n"
    ]

    for i, (sub, listing) in enumerate(subs, 1):
        try:
            check_res = await orchestrator.check_listing(listing)
            title = html.escape(listing.product_title)
            if check_res.success and check_res.quote:
                q = check_res.quote
                price_str = f"₹{(q.price_paise or 0) / 100:,.0f}" if q.price_paise else "N/A"
                if q.available:
                    qty_str = f" ({q.inventory_quantity} units)" if q.inventory_quantity is not None else ""
                    stock_badge = f"🟢 In Stock{qty_str}"
                else:
                    time_info = ""
                    dt = q.last_in_stock_at or listing.last_in_stock_at
                    if dt:
                        time_info = f" (Last in stock: {format_ist_datetime(dt)})"
                    stock_badge = f"🔴 Out of Stock{time_info}"

                    # Cross-store in-stock check: Automatically discover if product is in stock elsewhere!
                    alt_info = ""
                    try:
                        discovery_svc: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
                        alt_deal = await discovery_svc.find_in_stock_alternative(listing)
                        if alt_deal and alt_deal.available and alt_deal.url:
                            alt_price = format_paise_to_inr(alt_deal.price_paise)
                            alt_info = (
                                f"\n   👉 🟢 <b>IN STOCK on {alt_deal.store_name}:</b> "
                                f"<code>{alt_price}</code> (<a href='{alt_deal.url}'>Direct Buy Link</a>)"
                            )
                    except Exception:
                        pass

                    results_lines.append(f"{i}. <b>{title}</b>\n   {stock_badge} | 💰 {price_str}{alt_info}")
            else:
                err_text = html.escape(check_res.error or "Check failed")
                results_lines.append(f"{i}. <b>{title}</b>\n   ⚠️ Check failed: {err_text}")
        except Exception as err:
            results_lines.append(f"{i}. <b>{html.escape(listing.product_title)}</b>\n   ⚠️ Error: {html.escape(str(err)[:60])}")

    results_lines.append("\n✅ <i>All tracked items refreshed with live store data!</i>")
    kb = build_action_nav_keyboard("📋 View Tracked List", "nav:tracked", "⚙️ Alert Settings", "cfg:refresh")
    await status_msg.edit_text(
        "\n".join(results_lines),
        reply_markup=kb,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
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
    kb = build_amul_category_keyboard(pincode=pincode)
    await update.effective_message.reply_html(text, reply_markup=kb)


async def search_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <query> across Amul products."""
    if not update.effective_user or not update.effective_message:
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        kb = build_search_suggestions_keyboard()
        await update.effective_message.reply_html(
            "🔍 <b>Usage:</b> <code>/search &lt;keyword&gt;</code>\n\n"
            "Tap any quick keyword below or type your search:",
            reply_markup=kb,
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
    for i, chunk in enumerate(messages):
        is_last = (i == len(messages) - 1)
        kb = build_action_nav_keyboard("⬅️ Back to Categories", "amul_menu", "⭐ Favourites", "nav:favs") if is_last else None
        await update.effective_message.reply_html(chunk, reply_markup=kb, disable_web_page_preview=True)


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
        kb = build_action_nav_keyboard("🥛 Browse Protein", "amul_cat:protein", "🔍 Search", "nav:search")
        await update.effective_message.reply_html(
            "⭐ <b>You have no favourites yet.</b>\n\n"
            "Browse products with <code>/products</code> or search with <code>/search</code> and tap <b>[Favourite]</b> on any item to save it here!",
            reply_markup=kb,
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
    for i, chunk in enumerate(messages):
        is_last = (i == len(messages) - 1)
        kb = build_action_nav_keyboard("🥛 Browse All Products", "amul_menu", "⚙️ Alert Settings", "cfg:refresh") if is_last else None
        await update.effective_message.reply_html(chunk, reply_markup=kb, disable_web_page_preview=True)


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
        kb = build_repeat_keyboard(user.max_notify_count)
        await update.effective_message.reply_html(
            "🔁 <b>Repeated Stock Alerts Configuration</b>\n\n"
            f"• Current setting: <b>{cur_str}</b>\n\n"
            "<b>Tap a quick option below</b> or send <code>/repeat &lt;1-10 or 0&gt;</code>:\n"
            "• <code>/repeat 1</code> to <code>10</code> - Receive up to N dynamic updates as stock decreases.\n"
            "• <code>/repeat 0</code> (or <code>oos</code>) - Continuous alerts until sold out.",
            reply_markup=kb,
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

    from pricewatch.services.sparkline import format_price_trend_summary
    obs_prices = [obs.price_paise for obs in observations if obs.price_paise]
    trend_line = format_price_trend_summary(obs_prices, listing.last_price_paise) or ""

    if not chart_bytes:
        msg = (
            f"📈 <b>Price History: {html.escape(listing.product_title)}</b>\n\n"
            f"💰 <b>Current:</b> ₹{(listing.last_price_paise or 0)/100:,.0f} | "
            f"🎯 <b>Target:</b> ₹{(target_paise or 0)/100:,.0f}\n\n"
        )
        if trend_line:
            msg += f"{trend_line}\n\n"
        msg += f"🔗 <a href='{listing.canonical_url}'>Open Store Page</a>"
        await status_msg.edit_text(msg, parse_mode="HTML")
        return

    await status_msg.delete()
    caption_parts = [
        f"📈 <b>Price History: {html.escape(listing.product_title)}</b>",
        f"💰 <b>Current:</b> ₹{(listing.last_price_paise or 0)/100:,.0f} | 🎯 <b>Target:</b> ₹{(target_paise or 0)/100:,.0f}",
    ]
    if trend_line:
        caption_parts.append(trend_line)
    caption_parts.append(f"🔗 <a href='{listing.canonical_url}'>Open Store Page</a>")

    await update.effective_message.reply_photo(
        photo=chart_bytes,
        caption="\n".join(caption_parts),
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
            kb = build_listing_card_keyboard(listing.id, is_nutrabay=(listing.provider_code == "nutrabay"))
            await update.effective_message.reply_html(conf_text, reply_markup=kb)
            if listing.last_available is False:
                import asyncio
                asyncio.create_task(
                    notify_if_available_elsewhere(
                        chat_id=update.effective_chat.id,
                        user_id=update.effective_user.id,
                        listing=listing,
                        context=context,
                    )
                )
            return
        except Exception as exc:
            await update.effective_message.reply_html(f"❌ Failed to set target price: {exc}")
            return

    # 2. Check if user is in /compare query input state
    if context.user_data.pop("awaiting_compare_query", False):
        discovery_service: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
        status_msg = await update.effective_message.reply_html(
            f"🔍 <i>Searching across trusted stores for:</i>\n<b>{html.escape(text)}</b>..."
        )
        try:
            result = await discovery_service.compare_query(text)
            report_text = format_comparison_report(result)
            kb = build_comparison_keyboard(result)
            await status_msg.edit_text(
                report_text,
                reply_markup=kb,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return
        except Exception as exc:
            safe_exc = html.escape(str(exc))
            await status_msg.edit_text(
                f"❌ <b>Price comparison error:</b>\n{safe_exc}",
                parse_mode="HTML",
            )
            return

    # 3. Check if user is in /instock query input state
    if context.user_data.pop("awaiting_instock_query", False):
        discovery_service: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
        status_msg = await update.effective_message.reply_html(
            f"⚡ <i>Checking real-time stock across stores for:</i>\n<b>{html.escape(text)}</b>..."
        )
        try:
            result = await discovery_service.compare_query(text)
            report_text = format_instock_report(result)
            kb = build_instock_keyboard(result)
            await status_msg.edit_text(
                report_text,
                reply_markup=kb,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return
        except Exception as exc:
            safe_exc = html.escape(str(exc))
            await status_msg.edit_text(
                f"❌ <b>Stock check error:</b>\n{safe_exc}",
                parse_mode="HTML",
            )
            return

    # 3. Check if user is awaiting URL or message contains a product URL
    is_awaiting_url = context.user_data.pop("awaiting_track_url", False)
    url_match = re.search(r"https?://[^\s]+", text)
    if url_match:
        url = url_match.group(0)
        await _inspect_url_and_prompt_modes(update, context, url)
        return
    elif is_awaiting_url:
        await update.effective_message.reply_html(
            "⚠️ That doesn't look like a valid link. Please send a full product URL starting with <code>https://</code>\n\n"
            "<b>Example:</b>\n<code>https://nutrabay.com/product/nutrabay-pure-shilajit/</code>",
            reply_markup=build_action_nav_keyboard("❌ Cancel", "trk:cancel", "🏠 Main Menu", "nav:home", include_home=False),
        )
        context.user_data["awaiting_track_url"] = True
        return
    else:
        # User typed plain text or asked a question
        kb = build_action_nav_keyboard("🥛 Browse Amul", "amul_menu", "📋 Tracked Items", "nav:tracked")
        await update.effective_message.reply_html(
            "👋 <b>PriceWatch Assistant</b>\n\n"
            "• 🔗 <b>Paste any product link</b> (Amazon, Nutrabay, Flipkart, MuscleBlaze, Shopify) directly here to track price and stock.\n"
            "• Or use the buttons below or Telegram <b>Menu</b> to explore:",
            reply_markup=kb,
        )
        return


async def notify_if_available_elsewhere(
    chat_id: int,
    user_id: int,
    listing: CanonicalListing,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Asynchronously checks other stores and alerts the user if an out-of-stock item is in stock elsewhere."""
    if listing.last_available is not False:
        return

    discovery_service: DiscoveryService = context.bot_data.get("discovery_service") or DiscoveryService()
    try:
        alt_deal = await discovery_service.find_in_stock_alternative(listing)
        if alt_deal and alt_deal.available and alt_deal.url:
            context.user_data[f"alt_deal_{listing.id}"] = alt_deal
            text = format_cross_store_alert(listing, alt_deal)
            kb = build_cross_store_alert_keyboard(listing.id, alt_deal)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
    except Exception:
        pass


async def _inspect_url_and_prompt_modes(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    """Inspects product URL and presents intuitive tracking mode options."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    status_msg = await update.effective_message.reply_text("🔍 Inspecting product URL...")

    try:
        ProviderRegistry.get_provider_for_url(url)
    except Exception as exc:
        safe_exc = html.escape(str(exc))
        await status_msg.edit_text(
            f"❌ <b>Unsupported store link:</b>\n{safe_exc}\n\n"
            "Supported stores: Nutrabay, Amazon, Amul Shop, and Shopify stores (Nakpro, MuscleBlaze, etc.).",
            parse_mode="HTML",
        )
        return

    try:
        # If Amul URL, resolve Amul listing
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
            preview_text = format_stepwise_product_preview(saved_listing)
            kb = build_tracking_mode_keyboard(
                listing_id=saved_listing.id,
                current_price_paise=saved_listing.last_price_paise or 0,
                is_in_stock=saved_listing.last_available if saved_listing.last_available is not None else True,
            )
            await status_msg.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
            return

        # For Nutrabay, Shopify, Amazon, etc.: Stepwise onboarding with tracking mode selection
        listing = await tracker_service.resolve_and_preview_url(
            telegram_id=update.effective_user.id,
            url=url,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

        preview_text = format_stepwise_product_preview(listing)
        kb = build_tracking_mode_keyboard(
            listing_id=listing.id,
            current_price_paise=listing.last_price_paise or 0,
            is_in_stock=listing.last_available if listing.last_available is not None else True,
            is_nutrabay=(listing.provider_code == "nutrabay"),
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
        safe_exc = html.escape(str(exc))
        await status_msg.edit_text(f"❌ <b>Failed to inspect link:</b>\n{safe_exc}", parse_mode="HTML")


async def channels_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /channels command to manage multi-channel alerts (Discord, NTFY, Slack, etc.)."""
    if not update.effective_user or not update.effective_message:
        return

    args = context.args or []
    user_id = update.effective_user.id
    user_channels = context.user_data.get("notification_channels", [])

    if not args:
        lines = [
            "📣 <b>Multi-Channel Notification Settings</b>\n",
            "PriceWatch can dispatch instant restock & price drop alerts to Discord, NTFY, Slack, and Webhooks alongside Telegram!\n",
            f"<b>Active Channels:</b> {len(user_channels)} custom channel(s)",
        ]
        if user_channels:
            for i, ch in enumerate(user_channels, 1):
                masked = ch[:18] + "..." if len(ch) > 20 else ch
                lines.append(f"{i}. <code>{html.escape(masked)}</code>")
        else:
            lines.append("<i>Only native Telegram alerts currently active.</i>")

        lines.extend([
            "\n<b>Supported Protocols:</b>",
            "• Discord: <code>/channels add discord://webhook_id/token</code>",
            "• NTFY: <code>/channels add ntfy://your_topic_name</code>",
            "• Slack: <code>/channels add slack://TokenA/TokenB/TokenC</code>",
            "• Pushover: <code>/channels add pover://user_key@token</code>",
            "\n<b>Commands:</b>",
            "• <code>/channels add &lt;url&gt;</code> - Add a notification channel",
            "• <code>/channels test</code> - Send a test alert to all connected channels",
            "• <code>/channels clear</code> - Remove all custom channels",
        ])
        kb = build_action_nav_keyboard("🧪 Test Channels", "channels:test", "⚙️ Alert Settings", "cfg:refresh")
        await update.effective_message.reply_html("\n".join(lines), reply_markup=kb)
        return

    subcmd = args[0].lower()
    if subcmd == "add":
        if len(args) < 2:
            await update.effective_message.reply_html(
                "⚠️ <b>Usage:</b> <code>/channels add &lt;service_url&gt;</code>\n"
                "Example: <code>/channels add ntfy://my_whey_alerts</code>"
            )
            return
        new_url = args[1].strip()
        if new_url not in user_channels:
            user_channels.append(new_url)
            context.user_data["notification_channels"] = user_channels
        masked = new_url[:20] + "..." if len(new_url) > 22 else new_url
        await update.effective_message.reply_html(
            f"✅ <b>Channel Added Successfully!</b>\n"
            f"Channel: <code>{html.escape(masked)}</code>\n\n"
            "Restock and price drop notifications will now be dispatched to this endpoint alongside Telegram."
        )
    elif subcmd == "clear":
        context.user_data["notification_channels"] = []
        await update.effective_message.reply_html("🗑️ <b>All custom notification channels cleared.</b> Native Telegram alerts remain active.")
    elif subcmd == "test":
        await update.effective_message.reply_html("🧪 <i>Dispatching test alert across all configured channels...</i>")
        ok = await multichannel_notifier.notify(
            title="PriceWatch Test Alert",
            body="<b>PriceWatch Test Alert</b>\nYour multi-channel notification pipeline is working perfectly!",
            channels=user_channels or None,
        )
        if ok:
            await update.effective_message.reply_html("✅ <b>Test notification sent successfully!</b> Check your Discord/NTFY channel.")
        else:
            await update.effective_message.reply_html("⚠️ <b>Test alert failed.</b> Please verify your channel URL syntax.")
    else:
        await update.effective_message.reply_html("⚠️ Unknown subcommand. Use <code>/channels</code> to view usage.")


async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photos/screenshots to detect products and offer 1-click tracking and comparisons."""
    if not update.effective_user or not update.effective_message or not update.message or not update.message.photo:
        return

    status_msg = await update.effective_message.reply_html(
        "📸 <i>Analyzing product screenshot with AI Vision...</i>"
    )

    try:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        img_bytes = await photo_file.download_as_bytearray()

        product = await vision_extractor.extract_from_image_bytes(bytes(img_bytes))
        if not product or not product.title:
            await status_msg.edit_text(
                "📸 <b>Screenshot received!</b>\n\n"
                "We couldn't automatically read the product name from this image. "
                "Please paste the product link directly or type the product name (e.g. <code>/compare Nakpro Whey</code>) to track it!",
                parse_mode="HTML",
            )
            return

        title = html.escape(product.title)
        brand = f" ({html.escape(product.brand)})" if product.brand else ""
        variant = f"\n🏷️ <b>Variant:</b> {html.escape(product.variant)}" if product.variant else ""
        price = f"\n💰 <b>Price in Screenshot:</b> ₹{product.price_paise / 100:,.0f}" if product.price_paise else ""

        # Trigger cross-store discovery for this product
        discovery_svc: DiscoveryService = context.bot_data.get("discovery_service", DiscoveryService())
        query = f"{product.title} {product.variant or ''}".strip()
        cmp_result = await discovery_svc.compare_query(query=query, target_weight_g=product.weight_g)

        lines = [
            "📸 <b>Product Detected via AI Vision!</b>\n",
            f"📦 <b>Product:</b> {title}{brand}{variant}{price}",
        ]

        if cmp_result and cmp_result.best_deal:
            bd = cmp_result.best_deal
            from pricewatch.validation.normalizer import format_paise_to_inr
            p_str = format_paise_to_inr(bd.price_paise)
            lines.append(f"\n🏆 <b>Best Live Deal Found:</b>\n👉 <b>{bd.store_name}:</b> <code>{p_str}</code> (🟢 <b>In Stock</b>)")

        lines.append("\n<i>Tap below to compare all stores or track this product:</i>")

        kb = build_comparison_keyboard(cmp_result)
        await status_msg.edit_text(
            "\n".join(lines),
            reply_markup=kb,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    except Exception as exc:
        logger.warning("Error processing photo message", error=str(exc))
        await status_msg.edit_text(
            "⚠️ <b>Could not process image.</b> Please paste the product link directly to track!",
            parse_mode="HTML",
        )


