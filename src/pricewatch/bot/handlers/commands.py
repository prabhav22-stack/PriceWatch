"""Telegram command handlers (/start, /help, /track, /list, /untrack, /pincode, /status)."""

import re
from telegram import Update
from telegram.ext import ContextTypes

from pricewatch.bot.formatters import (
    format_help_message,
    format_subscription_list,
    format_tracking_confirmation,
    format_welcome_message,
)
from pricewatch.bot.keyboards import build_variant_selection_keyboard
from pricewatch.domain.exceptions import VariantAmbiguousError
from pricewatch.services.tracker_service import TrackerService
from pricewatch.validation.normalizer import parse_inr_to_paise


_PINCODE_REGEX = re.compile(r"^\d{6}$")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.effective_user or not update.effective_message:
        return

    tracker_service: TrackerService = context.bot_data["tracker_service"]
    user = update.effective_user
    await tracker_service.get_or_register_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

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
        "• <b>Database:</b> Coordinated PostgreSQL Lease Locks"
    )
