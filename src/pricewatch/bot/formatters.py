"""HTML message templates and formatters for Telegram."""

from typing import List, Tuple

from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.validation.normalizer import format_paise_to_inr


def format_welcome_message(first_name: str = "there") -> str:
    return (
        f"👋 <b>Welcome to PriceWatch 2.0, {first_name}!</b>\n\n"
        "I track prices across Indian e-commerce stores (Nakpro, MuscleBlaze, Amazon, etc.) "
        "and alert you the moment a product drops to your target price.\n\n"
        "<b>Quick Start:</b>\n"
        "• Send <code>/track &lt;url&gt; &lt;target_price&gt; [pincode]</code>\n"
        "• Example: <code>/track https://nakpro.com/products/impact-whey 1200</code>\n"
        "• Use <code>/list</code> to see your tracked products\n"
        "• Use <code>/pincode 842002</code> to set your default pincode\n"
        "• Use <code>/help</code> for all commands"
    )


def format_help_message() -> str:
    return (
        "📖 <b>PriceWatch 2.0 Commands</b>\n\n"
        "<b>Tracking:</b>\n"
        "• <code>/track &lt;url&gt; &lt;target_price&gt; [pincode]</code>\n"
        "  Start tracking a product. If the item has multiple variants (flavors/sizes), "
        "I'll prompt you with buttons to pick your exact variant.\n\n"
        "<b>Management:</b>\n"
        "• <code>/list</code> - View your active tracked items with live prices\n"
        "• <code>/untrack &lt;id&gt;</code> - Stop tracking a specific item\n"
        "• <code>/pincode &lt;6-digit&gt;</code> - Set your default delivery pincode\n"
        "• <code>/status</code> - View system status and check frequency\n"
        "• <code>/help</code> - Show this guide"
    )


def format_tracking_confirmation(listing: CanonicalListing, sub: Subscription) -> str:
    price_str = format_paise_to_inr(listing.last_price_paise)
    target_str = format_paise_to_inr(sub.target_price_paise)
    mrp_str = format_paise_to_inr(listing.last_mrp_paise) if listing.last_mrp_paise else None

    lines = [
        "✅ <b>Now Tracking Product!</b>",
        "",
        f"📦 <b>Title:</b> {listing.product_title}",
    ]
    if listing.variant_title and listing.variant_title != "Default":
        lines.append(f"🏷️ <b>Variant:</b> {listing.variant_title}")

    lines.extend([
        f"💰 <b>Current Price:</b> <code>{price_str}</code>",
        f"🎯 <b>Your Alert Target:</b> <code>{target_str}</code>",
    ])
    if mrp_str:
        lines.append(f"🏷️ <b>MRP:</b> <s>{mrp_str}</s>")
    if listing.pincode:
        lines.append(f"📍 <b>Pincode:</b> <code>{listing.pincode}</code>")

    lines.extend([
        "",
        f"🆔 <b>Listing ID:</b> <code>{listing.id}</code> (use <code>/untrack {listing.id}</code> to remove)",
        f'🔗 <a href="{listing.canonical_url}">Open Store Link</a>',
    ])
    return "\n".join(lines)


def format_subscription_list(items: List[Tuple[Subscription, CanonicalListing]]) -> str:
    if not items:
        return (
            "📭 <b>You have no active tracked products.</b>\n\n"
            "Use <code>/track &lt;url&gt; &lt;target_price&gt;</code> to start tracking!"
        )

    lines = [f"📋 <b>Your Tracked Products ({len(items)}):</b>", ""]
    for i, (sub, listing) in enumerate(items, 1):
        price_str = format_paise_to_inr(listing.last_price_paise)
        target_str = format_paise_to_inr(sub.target_price_paise)
        variant = f" ({listing.variant_title})" if listing.variant_title and listing.variant_title != "Default" else ""

        status_icon = "🟢" if listing.last_available else "🔴 OOS"
        lines.append(
            f"{i}. <b>{listing.product_title}</b>{variant}\n"
            f"   {status_icon} Current: <code>{price_str}</code> | Target: <code>{target_str}</code>\n"
            f"   🆔 ID: <code>{listing.id}</code> | /untrack_{listing.id}"
        )
        lines.append("")

    return "\n".join(lines)
