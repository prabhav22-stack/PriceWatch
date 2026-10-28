"""Inline keyboard callback query handlers for stepwise onboarding, price charts, and Amul stock."""

from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_amul_category_menu,
    format_amul_category_messages,
    format_amul_category_view,
    format_amul_favourites_messages,
    format_amul_search_messages,
    format_amul_tracking_confirmed,
    format_settings_menu,
    format_stepwise_product_preview,
    format_subscription_list,
    format_tracking_confirmation,
    format_tracking_mode_confirmation,
)
from pricewatch.bot.keyboards import (
    build_action_nav_keyboard,
    build_amul_category_keyboard,
    build_amul_product_stock_keyboard,
    build_category_navigation_keyboard,
    build_listing_card_keyboard,
    build_pincode_keyboard,
    build_search_suggestions_keyboard,
    build_settings_keyboard,
    build_target_price_keyboard,
    build_tracking_mode_keyboard,
)
from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.logging_setup import get_logger
from pricewatch.providers.amul import AMUL_CATEGORIES, AmulProvider
from pricewatch.services.amul_stock_tracker import AmulStockTracker
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
        # Cancel tracking prompt: trk:cancel
        if data == "trk:cancel":
            context.user_data.pop("awaiting_track_url", None)
            context.user_data.pop("awaiting_custom_price", None)
            context.user_data.pop("pending_track_variants", None)
            context.user_data.pop("pending_track", None)
            await query.edit_message_text("❌ Product tracking cancelled.")
            return

        # Tracking mode selection: trk_mode:<listing_id>:<mode>
        if data.startswith("trk_mode:"):
            parts = data.split(":")
            listing_id = int(parts[1])
            mode = parts[2]

            listing = await tracker_service.get_listing(listing_id)
            if not listing:
                await query.edit_message_text("❌ Product listing not found.")
                return

            if mode == "target":
                target_kb = build_target_price_keyboard(
                    listing_id=listing_id,
                    current_price_paise=listing.last_price_paise or 0,
                )
                await query.edit_message_text(
                    "🎯 <b>What target price would you like to set for alert?</b>\n\n"
                    "<i>Select a quick discount option below or choose Custom Price:</i>",
                    reply_markup=target_kb,
                    parse_mode="HTML",
                )
                return

            if mode == "back":
                preview_text = format_stepwise_product_preview(listing)
                mode_kb = build_tracking_mode_keyboard(
                    listing_id=listing.id,
                    current_price_paise=listing.last_price_paise or 0,
                    is_in_stock=listing.last_available if listing.last_available is not None else True,
                )
                await query.edit_message_text(preview_text, reply_markup=mode_kb, parse_mode="HTML")
                return

            # Combined Auto-Tracker mode (watches both restocks and significant discounts)
            target_paise = listing.last_price_paise or 1
            is_in_stock = bool(listing.last_available)
            alert_rearmed = not is_in_stock if not is_in_stock else True

            sub = Subscription(
                telegram_id=user_id,
                listing_id=listing_id,
                target_price_paise=target_paise,
                notify_on_restock=True,
                is_active=True,
                alert_rearmed=alert_rearmed,
                last_alerted_price_paise=listing.last_price_paise if is_in_stock else None,
            )
            saved_sub = await tracker_service.sub_repo.create_or_update_subscription(sub)
            context.user_data.pop("awaiting_custom_price", None)
            conf_text = format_tracking_mode_confirmation(listing, saved_sub, mode)
            kb = build_listing_card_keyboard(listing_id)
            await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="HTML")
            return

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
            listing = await tracker_service.get_listing(listing_id)
            title = listing.product_title if listing else f"Listing #{listing_id}"
            await tracker_service.untrack_product(user_id, listing_id)
            await query.edit_message_text(
                f"🔍 <b>Untracking product: {title}</b>\n"
                f"You will no longer receive updates for this product.",
                parse_mode="HTML",
            )
            return

        if data == "del:cancel":
            await query.edit_message_text("Tracking unchanged.")
            return

        # 5. Amul Categories Menu
        if data == "amul_menu":
            try:
                await query.answer()
            except Exception:
                pass
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode = user.default_pincode or "842002"
            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(pincode)

            text = format_amul_category_menu(pincode=pincode, substore=substore)
            kb = build_amul_category_keyboard(pincode=pincode)
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # 6. Amul Category Product View: amul_cat:<cat_id>
        if data.startswith("amul_cat:"):
            cat_id = data.split(":")[1]
            cat_info = next(
                (c for c in AMUL_CATEGORIES if c["id"] == cat_id),
                {"label": cat_id.title(), "emoji": "💪"},
            )
            try:
                await query.answer(f"{cat_info['label']} products")
            except Exception:
                pass

            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode = user.default_pincode or "842002"

            # Safely delete the category menu message matching upstream amul-notify
            try:
                await query.message.delete()
            except Exception:
                pass

            wait_msg = None
            cache_key = (cat_id, pincode)
            if cache_key not in AmulProvider._cls_category_cache:
                try:
                    wait_msg = await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"⏳ Fetching <b>{cat_info['label']}</b> from Amul... Please wait...",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(pincode)
            # Fetch ALL category products (limit=100) with connection pooling and caching
            products = await amul_provider.fetch_category_products(cat_id, pincode=pincode, limit=100)

            # Record live stock observations and retrieve history
            stock_tracker = AmulStockTracker.get_instance()
            await stock_tracker.load_history_for_substore(substore)
            stock_tracker.record_batch_observations(products, substore=substore)
            stock_histories = {
                p.get("sku"): stock_tracker.get_history(p.get("sku", ""), substore)
                for p in products
                if p.get("sku")
            }

            user_subs = await tracker_service.list_user_subscriptions(user_id)
            tracked_skus = {s[1].external_variant_id for s in user_subs if s[1].provider_code == "amul"}
            favourite_skus = set(user.favourite_skus or [])
            bot_username = context.bot.username or "wheypricewatch_bot"

            messages = format_amul_category_messages(
                category_label=cat_info["label"],
                category_emoji=cat_info.get("emoji", "💪"),
                pincode=pincode,
                substore=substore,
                products=products,
                tracked_skus=tracked_skus,
                bot_username=bot_username,
                stock_histories=stock_histories,
                favourite_skus=favourite_skus,
            )

            if wait_msg:
                try:
                    await wait_msg.delete()
                except Exception:
                    pass

            # Deliver all chunked messages cleanly with bottom navigation keyboard on final chunk
            for i, chunk in enumerate(messages):
                is_last = (i == len(messages) - 1)
                kb = build_category_navigation_keyboard(cat_id) if is_last else None
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return

        # Navigation: nav:favs
        if data == "nav:favs":
            try:
                await query.answer()
            except Exception:
                pass
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            fav_skus = set(user.favourite_skus or [])
            pincode = user.default_pincode or "842002"

            if not fav_skus:
                kb = build_action_nav_keyboard("🥛 Browse Protein", "amul_cat:protein", "🔍 Search", "nav:search")
                try:
                    await query.edit_message_text(
                        "⭐ <b>You have no favourites yet.</b>\n\n"
                        "Browse products with <code>/products</code> or search with <code>/search</code> and tap <b>[Favourite]</b> on any item to save it here!",
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        raise
                return

            try:
                await query.message.delete()
            except Exception:
                pass

            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(pincode)
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

            user_subs = await tracker_service.list_user_subscriptions(user_id)
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

            for i, chunk in enumerate(messages):
                is_last = (i == len(messages) - 1)
                kb = build_action_nav_keyboard("🥛 Browse All Products", "amul_menu", "⚙️ Alert Settings", "cfg:refresh") if is_last else None
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            return

        # Navigation: nav:tracked
        if data == "nav:tracked":
            try:
                await query.answer()
            except Exception:
                pass
            items = await tracker_service.list_user_subscriptions(user_id)
            text = format_subscription_list(items)
            kb = (
                build_action_nav_keyboard("🥛 Browse Products", "amul_menu", "⭐ Favourites", "nav:favs")
                if not items
                else build_action_nav_keyboard("🥛 Add More Products", "amul_menu", "⚙️ Alert Settings", "cfg:refresh")
            )
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Navigation: nav:live_check
        if data == "nav:live_check":
            try:
                await query.answer("Running live check...")
            except Exception:
                pass
            from pricewatch.bot.handlers.commands import check_command_handler
            await check_command_handler(update, context)
            return

        # Navigation: nav:search
        if data == "nav:search":
            try:
                await query.answer()
            except Exception:
                pass
            text = (
                "🔍 <b>Amul Product Quick Search</b>\n\n"
                "Tap any popular search keyword below or type <code>/search &lt;keyword&gt;</code>:"
            )
            kb = build_search_suggestions_keyboard()
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Navigation: nav:pincode
        if data == "nav:pincode":
            try:
                await query.answer()
            except Exception:
                pass
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            curr_pin = user.default_pincode or "842002"
            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(curr_pin)
            text = (
                f"📍 <b>Delivery Hub & Pincode</b>\n\n"
                f"• Current Pincode: <b>{curr_pin}</b> (Warehouse: <i>{substore}</i>)\n\n"
                "Tap a quick hub below to switch warehouse stock, or type <code>/setpincode &lt;6-digit&gt;</code>:"
            )
            kb = build_pincode_keyboard(curr_pin)
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Quick Hub Switcher: set_pin:<pincode>
        if data.startswith("set_pin:"):
            new_pin = data.split(":")[1]
            await tracker_service.set_user_pincode(user_id, new_pin)
            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(new_pin)
            try:
                await query.answer(f"Pincode set to {new_pin} ({substore}) ✅")
            except Exception:
                pass
            text = (
                f"📍 <b>Delivery Hub & Pincode</b>\n\n"
                f"• Current Pincode: <b>{new_pin}</b> (Warehouse: <i>{substore}</i>) ✅\n\n"
                "Tap a quick hub below to switch warehouse stock, or type <code>/setpincode &lt;6-digit&gt;</code>:"
            )
            kb = build_pincode_keyboard(new_pin)
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Quick Search: quick_search:<term>
        if data.startswith("quick_search:"):
            term = data.split(":")[1]
            try:
                await query.answer(f"Searching for {term}...")
            except Exception:
                pass

            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            pincode = user.default_pincode or "842002"

            try:
                await query.message.delete()
            except Exception:
                pass

            amul_provider = AmulProvider()
            substore = await amul_provider.resolve_substore_for_pincode(pincode)
            products = await amul_provider.search_products(term, pincode=pincode)

            stock_tracker = AmulStockTracker.get_instance()
            await stock_tracker.load_history_for_substore(substore)
            stock_tracker.record_batch_observations(products, substore=substore)
            stock_histories = {
                p.get("sku"): stock_tracker.get_history(p.get("sku", ""), substore)
                for p in products
                if p.get("sku")
            }

            user_subs = await tracker_service.list_user_subscriptions(user_id)
            tracked_skus = {s[1].external_variant_id for s in user_subs if s[1].provider_code == "amul"}
            fav_skus = set(user.favourite_skus or [])
            ao_skus = set(user.auto_order_skus or [])
            bot_username = context.bot.username or "wheypricewatch_bot"

            messages = format_amul_search_messages(
                query=term,
                pincode=pincode,
                substore=substore,
                products=products,
                tracked_skus=tracked_skus,
                favourite_skus=fav_skus,
                auto_order_skus=ao_skus,
                bot_username=bot_username,
                stock_histories=stock_histories,
            )

            for i, chunk in enumerate(messages):
                is_last = (i == len(messages) - 1)
                kb = build_action_nav_keyboard("⬅️ Back to Categories", "amul_menu", "⭐ Favourites", "nav:favs") if is_last else None
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
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
                    telegram_id=user_id,
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
            await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="HTML")
            return

        # 8. Amul Untrack: amul_untrack:<sku>
        if data.startswith("amul_untrack:"):
            sku = data.split(":")[1]
            user_subs = await tracker_service.list_user_subscriptions(user_id)
            match = next((s for s in user_subs if s[1].provider_code == "amul" and s[1].external_variant_id == sku), None)
            if match:
                prod_title = match[1].product_title
                await tracker_service.untrack_product(user_id, match[1].id)
                await query.edit_message_text(
                    f"🔍 <b>Untracking product: {prod_title}</b>\n"
                    f"You will no longer receive updates for this product.",
                    parse_mode="HTML",
                )
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

        # 10. Settings Configuration Callbacks
        if data.startswith("cfg:"):
            cfg_action = data.replace("cfg:", "")
            user = await tracker_service.get_or_register_user(telegram_id=user_id)
            toast_text = "Settings updated ✅"

            if cfg_action == "toggle_style":
                new_style = "once" if user.tracking_style == "always" else "always"
                user = await tracker_service.update_user_settings(user_id, tracking_style=new_style)
                toast_text = f"Tracking style: {new_style.capitalize()} 🔄"
            elif cfg_action.startswith("style:"):
                new_style = cfg_action.split(":")[1]
                user = await tracker_service.update_user_settings(user_id, tracking_style=new_style)
                toast_text = f"Tracking style: {new_style.capitalize()}"
            elif cfg_action.startswith("max:") or cfg_action.startswith("repeat:"):
                new_max = int(cfg_action.split(":")[1])
                user = await tracker_service.update_user_settings(user_id, max_notify_count=new_max)
                toast_text = f"Repeat limit: {'Until OOS ♾️' if new_max == 0 else f'{new_max} alerts'}"
            elif cfg_action == "toggle_ao":
                new_ao = not user.auto_order_enabled
                user = await tracker_service.update_user_settings(user_id, auto_order_enabled=new_ao)
                toast_text = f"Auto-Order: {'Enabled 🟢' if new_ao else 'Disabled ⚪'}"
            elif cfg_action == "toggle_all_protein":
                favs = list(user.favourite_skus or [])
                if "ALL_PROTEIN" in favs:
                    favs.remove("ALL_PROTEIN")
                    toast_text = "All-Protein alerts: Disabled 🔕"
                else:
                    favs.append("ALL_PROTEIN")
                    toast_text = "All-Protein alerts: Activated 🔔"
                user = await tracker_service.update_user_settings(user_id, favourite_skus=favs)
            elif cfg_action == "refresh":
                toast_text = "Settings refreshed 🔄"

            text = format_settings_menu(user)
            kb = build_settings_keyboard(user)
            try:
                await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as edit_err:
                if "Message is not modified" not in str(edit_err):
                    logger.warning("Error updating settings message", error=str(edit_err))

            try:
                await query.answer(toast_text)
            except Exception:
                pass
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
        err_msg = str(exc)
        if "Message is not modified" in err_msg or "Query is too old" in err_msg:
            return
        logger.exception("Failed to process callback query", data=data, error=err_msg)
        try:
            await query.edit_message_text(f"❌ Error: {exc}")
        except Exception:
            pass
