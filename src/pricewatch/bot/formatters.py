"""HTML message templates and formatters for Telegram."""

from typing import List, Optional, Set, Tuple

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


def format_amul_category_menu(pincode: str = "842002", substore: str = "bihar") -> str:
    """Format Amul category selector menu header (matches vendor/amul-notify screenshot)."""
    return (
        f"<b>Amul Products</b> ({pincode} - {substore})\n\n"
        "Select a category to view products."
    )


def chunk_text_blocks(
    blocks: List[str], max_length: int = 3800, separator: str = "\n\n"
) -> List[str]:
    """
    Split text blocks into multiple Telegram messages under 4096 char limit.
    Directly mirrors chunkTextBlocks in vendor/amul-notify/src/utils/telegram.util.ts
    """
    chunks: List[str] = []
    current_chunk = ""

    for block in blocks:
        next_chunk = f"{current_chunk}{separator}{block}" if current_chunk else block
        if current_chunk and len(next_chunk) > max_length:
            chunks.append(current_chunk)
            current_chunk = block
            continue
        current_chunk = next_chunk

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def render_amul_product_item(
    product: dict,
    index: int,
    is_tracked: bool = False,
    bot_username: str = "wheypricewatch_bot",
    show_protein: bool = True,
) -> str:
    """
    Render a single Amul product block matching the exact format from the user's screenshot.
    """
    sku = product.get("sku") or ""
    name = product.get("name") or "Amul Product"
    url = product.get("url") or f"https://shop.amul.com/en/browse/product/{sku}"
    price_rs = (product.get("price_paise") or 0) // 100
    is_avail = bool(product.get("available", False))
    qty = product.get("inventory_quantity", 0)
    protein = product.get("protein") or "N/A"
    stock_icon = "🟢" if is_avail else "🔴"
    stock_text = f"Yes {stock_icon}" if is_avail else f"No {stock_icon}"

    track_url = f"https://t.me/{bot_username}?start=track_{sku}"
    untrack_url = f"https://t.me/{bot_username}?start=untrack_{sku}"
    action_link = (
        f'<b><a href="{untrack_url}">[Untrack]</a></b>'
        if is_tracked
        else f'<b><a href="{track_url}">[Track]</a></b>'
    )

    lines = [
        f'{index}. <b><a href="{url}">{name}</a></b>',
    ]
    if show_protein:
        lines.append(f"     Protein: <b>{protein}</b>")

    lines.extend([
        f"     Price: <b>{price_rs}₹</b>",
        f"     In Stock: <b>{stock_text}</b>",
        f"     Available Quantity: <b>{qty}</b>",
        f"{action_link} | <b><a href=\"{track_url}\">[Favourite]</a></b>",
    ])
    return "\n".join(lines)


def format_amul_category_messages(
    category_label: str,
    category_emoji: str,
    pincode: str,
    substore: str,
    products: List[dict],
    tracked_skus: Set[str],
    bot_username: str = "wheypricewatch_bot",
) -> List[str]:
    """
    Build clean chunked messages containing ALL products in the category without missing any.
    """
    title = f"<b>Amul {category_emoji} {category_label} Products</b> ({pincode} - {substore})"
    show_protein = category_label.lower() == "protein"

    blocks = [
        render_amul_product_item(
            product=p,
            index=i,
            is_tracked=p.get("sku") in tracked_skus,
            bot_username=bot_username,
            show_protein=show_protein,
        )
        for i, p in enumerate(products, 1)
    ]

    if not blocks:
        return [f"{title}\n\nNo products found for this category."]

    first_block = f"{title}\n\n{blocks[0]}"
    all_blocks = [first_block] + blocks[1:]
    return chunk_text_blocks(all_blocks, max_length=3800)


def format_amul_category_view(
    category_label: str, pincode: str, substore: str, products: List[dict]
) -> str:
    lines = [
        f"🥛 <b>Amul {category_label} Products</b>",
        f"📍 <b>Delivery Hub:</b> <code>{pincode}</code> (Substore: <i>{substore}</i>)",
        "",
        "<i>Real-time warehouse inventory:</i>",
    ]
    for i, p in enumerate(products, 1):
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
