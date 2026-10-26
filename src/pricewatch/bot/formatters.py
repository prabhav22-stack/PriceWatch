"""HTML message templates and formatters for Telegram."""

from typing import List, Optional, Tuple

from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.validation.normalizer import format_paise_to_inr


def format_welcome_message(first_name: str = "there") -> str:
    return (
        f"👋 <b>Welcome to PriceWatch 2.0, {first_name}!</b>\n\n"
        "I track prices and stock availability across Indian e-commerce stores:\n"
        "• <b>Amazon & Amazon Fresh</b> (hyperlocal pincodes)\n"
        "• <b>Amul Shop</b> (exclusive real-time stock & inventory alerts)\n"
        "• <b>Nakpro, MuscleBlaze, Shopify stores</b>\n\n"
        "<b>How to Use:</b>\n"
        "• 🔗 <b>Just paste any product link here</b> — I'll inspect it and let you pick your target price!\n"
        "• 🥛 Type <code>/amul</code> to browse & track live Amul protein stock\n"
        "• 📋 <code>/list</code> - View your active tracking list\n"
        "• 📍 <code>/pincode 110001</code> - Set your default delivery pincode\n"
        "• 📊 <code>/history &lt;id&gt;</code> - View 3-day price trend chart\n"
        "• 💡 Or use <code>/track &lt;url&gt; &lt;target_price&gt;</code> directly"
    )


def format_help_message() -> str:
    return (
        "📖 <b>PriceWatch 2.0 Commands</b>\n\n"
        "<b>Tracking Products:</b>\n"
        "• <b>Send Any Link:</b> Just paste an Amazon, Nakpro, or store link in chat!\n"
        "• <code>/track &lt;url&gt; &lt;target_price&gt; [pincode]</code>\n"
        "• <code>/amul</code> - Browse Amul products & track stock in 1-click\n\n"
        "<b>Management & Analytics:</b>\n"
        "• <code>/list</code> - View your active items with live prices\n"
        "• <code>/history &lt;id&gt;</code> - Generate visual price history chart\n"
        "• <code>/untrack &lt;id&gt;</code> - Stop tracking an item\n"
        "• <code>/pincode &lt;6-digit&gt;</code> - Set your delivery pincode\n"
        "• <code>/status</code> - View system health & background checks"
    )


def format_stepwise_product_preview(listing: CanonicalListing) -> str:
    price_str = format_paise_to_inr(listing.last_price_paise)
    mrp_str = format_paise_to_inr(listing.last_mrp_paise) if listing.last_mrp_paise else None

    lines = [
        "🔍 <b>Product Found!</b>",
        "",
        f"📦 <b>Title:</b> {listing.product_title}",
    ]
    if listing.variant_title and listing.variant_title != "Default":
        lines.append(f"🏷️ <b>Variant:</b> {listing.variant_title}")

    lines.append(f"💰 <b>Current Price:</b> <code>{price_str}</code>")
    if mrp_str and listing.last_price_paise and listing.last_mrp_paise and listing.last_mrp_paise > listing.last_price_paise:
        disc = int(round((listing.last_mrp_paise - listing.last_price_paise) * 100 / listing.last_mrp_paise))
        lines.append(f"🏷️ <b>MRP:</b> <s>{mrp_str}</s> (<b>{disc}% OFF</b>)")

    if listing.pincode:
        lines.append(f"📍 <b>Delivery Pincode:</b> <code>{listing.pincode}</code>")

    lines.extend([
        "",
        "🎯 <b>What target price would you like to set for alert?</b>",
        "<i>Select a quick discount option below or type a custom price:</i>",
    ])
    return "\n".join(lines)


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
            "Just paste any product link here or use <code>/amul</code> to start tracking!"
        )

    lines = [f"📋 <b>Your Tracked Products ({len(items)}):</b>", ""]
    for i, (sub, listing) in enumerate(items, 1):
        price_str = format_paise_to_inr(listing.last_price_paise)
        target_str = format_paise_to_inr(sub.target_price_paise)
        variant = f" ({listing.variant_title})" if listing.variant_title and listing.variant_title != "Default" else ""

        if listing.provider_code == "amul":
            stock_badge = "🟢 In Stock" if listing.last_available else "🔴 OOS"
            lines.append(
                f"{i}. 🥛 <b>{listing.product_title}</b>{variant}\n"
                f"   {stock_badge} | Stock Tracker (Pincode: {listing.pincode})\n"
                f"   🆔 ID: <code>{listing.id}</code> | /untrack_{listing.id}"
            )
        else:
            status_icon = "🟢" if listing.last_available else "🔴 OOS"
            lines.append(
                f"{i}. <b>{listing.product_title}</b>{variant}\n"
                f"   {status_icon} Current: <code>{price_str}</code> | Target: <code>{target_str}</code>\n"
                f"   🆔 ID: <code>{listing.id}</code> | /history_{listing.id} | /untrack_{listing.id}"
            )
        lines.append("")

    return "\n".join(lines)


def format_amul_category_view(
    category_label: str, pincode: str, substore: str, products: List[dict]
) -> str:
    lines = [
        f"🥛 <b>Amul {category_label} Products</b>",
        f"📍 <b>Delivery Hub:</b> <code>{pincode}</code> (Substore: <i>{substore}</i>)",
        "",
        "<i>Real-time warehouse inventory:</i>",
    ]
    for i, p in enumerate(products[:12], 1):
        name = p.get("name", "Product")
        price = p.get("price_paise", 0) / 100.0 if p.get("price_paise") else 0
        avail = p.get("available", False)
        qty = p.get("inventory_quantity", 0)
        status_icon = f"🟢 In Stock: <b>{qty} units</b>" if avail else "🔴 <b>Out of Stock</b>"

        lines.append(f"{i}. <b>{name}</b>")
        lines.append(f"   {status_icon} | ₹{price:,.0f}")

    lines.extend([
        "",
        "👇 <b>Tap a button below to start/stop instant stock alerts:</b>"
    ])
    return "\n".join(lines)


def format_amul_tracking_confirmed(
    name: str, sku: str, pincode: str, available: bool, qty: int
) -> str:
    status_icon = f"🟢 In Stock ({qty} units)" if available else "🔴 Currently Out of Stock"
    return (
        "✅ <b>Amul Stock Tracker Activated!</b>\n\n"
        f"📦 <b>Product:</b> {name}\n"
        f"🏷️ <b>SKU:</b> <code>{sku}</code>\n"
        f"📍 <b>Pincode:</b> <code>{pincode}</code>\n"
        f"📊 <b>Status:</b> {status_icon}\n\n"
        "🔔 <i>You will receive an alert the second this product is restocked or inventory changes!</i>"
    )
