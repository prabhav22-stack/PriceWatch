"""HTML message templates and formatters for Telegram."""

from typing import Any, Dict, List, Optional, Set, Tuple

from pricewatch.domain.models import CanonicalListing, Subscription, User
from pricewatch.utils.time_utils import (
    format_duration,
    format_ist_datetime,
    format_relative_time,
)
from pricewatch.validation.normalizer import format_paise_to_inr


def format_welcome_message(first_name: str = "there") -> str:
    return (
        f"👋 <b>Welcome to PriceWatch 2.0, {first_name}!</b>\n\n"
        "I track prices and real-time stock availability across Indian e-commerce stores:\n"
        "• <b>Amul Shop</b> (exclusive real-time 60s restock watcher & dynamic alerts)\n"
        "• <b>Amazon & Amazon Fresh</b> (hyperlocal pincodes)\n"
        "• <b>Nakpro, MuscleBlaze, Shopify stores</b>\n\n"
        "<b>🥛 Amul Stock Watcher:</b>\n"
        "• <code>/products</code> - Browse products by category\n"
        "• <code>/tracked</code> - View your actively tracked items\n"
        "• <code>/trackall</code> - Toggle alerts for all protein products\n"
        "• <code>/repeat</code> - Configure repeat alerts (1-10 or continuous until OOS)\n"
        "• <code>/search &lt;query&gt;</code> - Search Amul catalog (e.g. <code>/search blueberry</code>)\n"
        "• <code>/favourites</code> - View your starred products\n"
        "• <code>/settings</code> - Notification preferences & tracking style\n"
        "• <code>/pincode 842002</code> - Set or view delivery pincode\n"
        "• <code>/count</code> - Real-time warehouse stock counts\n"
        "• <code>/analytics</code> - Warehouse inventory ratio & status\n\n"
        "<b>🛒 General Price Tracking:</b>\n"
        "• 🔗 <b>Just paste any product link here</b> to start tracking!\n"
        "• <code>/track &lt;url&gt; &lt;target_price&gt;</code> - Track with custom price target\n"
        "• <code>/untrack &lt;id&gt;</code> - Stop tracking an item\n"
        "• <code>/history &lt;id&gt;</code> - View price trend chart\n"
        "• <code>/help</code> - Complete command reference"
    )


def format_help_message() -> str:
    return (
        "📖 <b>PriceWatch 2.0 Commands</b>\n\n"
        "🥛 <b>Amul Stock Tracker:</b>\n"
        "• <code>/products</code> - Interactive category menu & stock\n"
        "• <code>/tracked</code> (or <code>/list</code>) - List your currently tracked products\n"
        "• <code>/trackall</code> - Toggle instant alerts for all protein items\n"
        "• <code>/repeat &lt;count&gt;</code> - Set repeated alert limit (1-10, or 0 for until OOS)\n"
        "• <code>/settings</code> - Interactive preferences menu & active checkmarks\n"
        "• <code>/pincode [pin]</code> - View or update your delivery pincode\n"
        "• <code>/setpincode &lt;pin&gt;</code> - Set your delivery pincode\n"
        "• <code>/favourites</code> - List your starred favourite products\n"
        "• <code>/search &lt;query&gt;</code> - Search Amul products by keyword\n"
        "• <code>/count</code> - Real-time available units per product\n"
        "• <code>/analytics</code> - Warehouse restock & inventory metrics\n"
        "• <code>/map</code> - View regional warehouse delivery hubs\n\n"
        "🛒 <b>General Stores (Amazon, Nakpro, Shopify):</b>\n"
        "• <b>Send Any Link:</b> Just paste a product URL directly in chat!\n"
        "• <code>/track &lt;url&gt; &lt;target_price&gt; [pincode]</code>\n"
        "• <code>/untrack [id]</code> - Choose or stop tracking an item\n"
        "• <code>/history [id]</code> - Generate visual price history chart\n"
        "• <code>/status</code> - System operational status & check frequency\n"
        "• <code>/support</code> - Community, GitHub repo & contact"
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
            title_link = (
                f'<a href="{listing.canonical_url}"><b>{listing.product_title}</b></a>'
                if listing.canonical_url and listing.canonical_url.startswith("http")
                else f"<b>{listing.product_title}</b>"
            )
            lines.append(
                f"{i}. 🥛 {title_link}{variant}\n"
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
    is_favourite: bool = False,
    is_auto_ordered: bool = False,
    bot_username: str = "wheypricewatch_bot",
    show_protein: bool = True,
    show_auto_order: bool = False,
    stock_history: Optional[Any] = None,
) -> str:
    """
    Render a single Amul product block matching the exact format from upstream amul-notify.
    Includes verified direct /en/product/ links, Last InStock / Out of Stock timestamps,
    and [Track] | [Favourite] and [Add Auto Order] action links.
    """
    sku = product.get("sku") or ""
    name = product.get("name") or "Amul Product"
    alias = (product.get("alias") or sku).strip().replace(" ", "")
    
    url = product.get("url")
    if not url or "/browse/product/" in url:
        url = f"https://shop.amul.com/en/product/{alias}" if alias else "https://shop.amul.com"

    price_rs = (product.get("price_paise") or 0) // 100
    is_avail = bool(product.get("available", False))
    qty = product.get("inventory_quantity", 0)
    protein = product.get("protein") or "N/A"
    stock_icon = "🟢" if is_avail else "🔴"
    stock_text = f"Yes {stock_icon}" if is_avail else f"No {stock_icon}"

    track_url = f"https://t.me/{bot_username}?start=track_{sku}"
    untrack_url = f"https://t.me/{bot_username}?start=untrack_{sku}"
    fav_url = f"https://t.me/{bot_username}?start=fav_{sku}"
    ao_url = f"https://t.me/{bot_username}?start=ao_{sku}"

    action_link = (
        f'<b><a href="{untrack_url}">[Untrack]</a></b>'
        if is_tracked
        else f'<b><a href="{track_url}">[Track]</a></b>'
    )
    fav_link = (
        f'<b><a href="{fav_url}">[Unfavourite]</a></b>'
        if is_favourite
        else f'<b><a href="{fav_url}">[Favourite]</a></b>'
    )
    ao_link = (
        f'<b><a href="{ao_url}">[Remove Auto Order]</a></b>'
        if is_auto_ordered
        else f'<b><a href="{ao_url}">[Add Auto Order]</a></b>'
    )

    lines = [
        f'{index}. <b><a href="{url}">{name}</a></b>',
    ]
    if show_protein:
        lines.append(f"     Protein: <b>{protein}</b>")

    lines.extend([
        f"     Price: <b>{price_rs}₹</b>",
        f"     In Stock: <b>{stock_text}</b>",
    ])

    # Extract stock history timestamps
    last_seen_in_stock_at = (
        getattr(stock_history, "last_seen_in_stock_at", None)
        or product.get("last_seen_in_stock_at")
    )
    last_seen_out_of_stock_at = (
        getattr(stock_history, "last_seen_out_of_stock_at", None)
        or product.get("last_seen_out_of_stock_at")
    )
    first_seen_in_stock_at = (
        getattr(stock_history, "first_seen_in_stock_at", None)
        or product.get("first_seen_in_stock_at")
    )

    if last_seen_in_stock_at:
        lines.append(
            f"     Last InStock: <b>{format_relative_time(last_seen_in_stock_at)} | {format_ist_datetime(last_seen_in_stock_at)}</b>"
        )
    if last_seen_out_of_stock_at:
        lines.append(
            f"     Last Out of Stock: <b>{format_relative_time(last_seen_out_of_stock_at)} | {format_ist_datetime(last_seen_out_of_stock_at)}</b>"
        )
    if first_seen_in_stock_at and last_seen_out_of_stock_at:
        lines.append(
            f"     In Stock Duration: <b>{format_duration(first_seen_in_stock_at, last_seen_out_of_stock_at)}</b>"
        )

    lines.extend([
        f"     Available Quantity: <b>{qty}</b>",
        f"{action_link} | {fav_link}",
    ])
    if show_auto_order:
        lines.append(ao_link)

    return "\n".join(lines)


def format_amul_category_messages(
    category_label: str,
    category_emoji: str,
    pincode: str,
    substore: str,
    products: List[dict],
    tracked_skus: Set[str],
    bot_username: str = "wheypricewatch_bot",
    stock_histories: Optional[Dict[str, Any]] = None,
    favourite_skus: Optional[Set[str]] = None,
    auto_order_skus: Optional[Set[str]] = None,
) -> List[str]:
    """
    Build clean chunked messages containing ALL products in the category without missing any.
    Includes quick inventory summary at top and stock status indicators.
    """
    in_stock_count = sum(1 for p in products if p.get("available"))
    oos_count = len(products) - in_stock_count
    title = (
        f"<b>Amul {category_emoji} {category_label} Products</b> ({pincode} - {substore})\n"
        f"🟢 <b>{in_stock_count} In Stock</b> | 🔴 <b>{oos_count} Out of Stock</b> ({len(products)} total)\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    show_protein = category_label.lower() == "protein"
    histories = stock_histories or {}
    favs = favourite_skus or set()
    ao_set = auto_order_skus or set()

    blocks = [
        render_amul_product_item(
            product=p,
            index=i,
            is_tracked=p.get("sku") in tracked_skus,
            is_favourite=p.get("sku") in favs,
            is_auto_ordered=p.get("sku") in ao_set,
            bot_username=bot_username,
            show_protein=show_protein,
            stock_history=histories.get(p.get("sku")),
        )
        for i, p in enumerate(products, 1)
    ]

    if not blocks:
        return [f"{title}\n\nNo products found for this category."]

    first_block = f"{title}\n\n{blocks[0]}"
    all_blocks = [first_block] + blocks[1:]
    return chunk_text_blocks(all_blocks, max_length=3800)


def format_amul_search_messages(
    query: str,
    pincode: str,
    substore: str,
    products: List[dict],
    tracked_skus: Set[str],
    favourite_skus: Optional[Set[str]] = None,
    auto_order_skus: Optional[Set[str]] = None,
    bot_username: str = "wheypricewatch_bot",
    stock_histories: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Format search results matching user query across all categories."""
    title = f"🔍 <b>Amul Search: \"{query}\"</b> ({pincode} - {substore})"
    histories = stock_histories or {}
    favs = favourite_skus or set()
    ao_set = auto_order_skus or set()

    if not products:
        return [f"{title}\n\nNo products found matching <b>{query}</b>."]

    blocks = [
        render_amul_product_item(
            product=p,
            index=i,
            is_tracked=p.get("sku") in tracked_skus,
            is_favourite=p.get("sku") in favs,
            is_auto_ordered=p.get("sku") in ao_set,
            bot_username=bot_username,
            show_protein=bool(p.get("protein") and p.get("protein") != "N/A"),
            stock_history=histories.get(p.get("sku")),
        )
        for i, p in enumerate(products, 1)
    ]

    first_block = f"{title}\n\nFound <b>{len(products)}</b> items:\n\n{blocks[0]}"
    all_blocks = [first_block] + blocks[1:]
    return chunk_text_blocks(all_blocks, max_length=3800)


def format_amul_favourites_messages(
    pincode: str,
    substore: str,
    products: List[dict],
    tracked_skus: Set[str],
    favourite_skus: Set[str],
    auto_order_skus: Optional[Set[str]] = None,
    bot_username: str = "wheypricewatch_bot",
    stock_histories: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Format user's starred favourite products."""
    title = f"⭐ <b>Your Favourite Amul Products</b> ({pincode} - {substore})"
    histories = stock_histories or {}
    ao_set = auto_order_skus or set()

    if not products:
        return [
            f"{title}\n\n"
            "You have no favourites yet.\n"
            "Browse products with <code>/amul</code> or search with <code>/search</code> and click <b>[Favourite]</b> to add them here!"
        ]

    blocks = [
        render_amul_product_item(
            product=p,
            index=i,
            is_tracked=p.get("sku") in tracked_skus,
            is_favourite=True,
            is_auto_ordered=p.get("sku") in ao_set,
            bot_username=bot_username,
            show_protein=bool(p.get("protein") and p.get("protein") != "N/A"),
            stock_history=histories.get(p.get("sku")),
        )
        for i, p in enumerate(products, 1)
    ]

    first_block = f"{title}\n\n{blocks[0]}"
    all_blocks = [first_block] + blocks[1:]
    return chunk_text_blocks(all_blocks, max_length=3800)


def format_amul_analytics(
    substore: str,
    pincode: str,
    products: List[dict],
    user_tracked_count: int = 0,
) -> str:
    """Format warehouse restock and inventory analytics."""
    total = len(products)
    in_stock = sum(1 for p in products if p.get("available"))
    out_of_stock = total - in_stock
    pct_avail = round((in_stock / total) * 100) if total else 0

    return (
        f"📊 <b>Amul Warehouse Analytics</b>\n"
        f"📍 <b>Delivery Hub:</b> <code>{pincode}</code> (Substore: <i>{substore}</i>)\n\n"
        f"🥛 <b>Protein Catalog Overview:</b>\n"
        f"• Total Catalog Items: <b>{total}</b>\n"
        f"• Currently In Stock: <b>{in_stock}</b> ({pct_avail}% 🟢)\n"
        f"• Currently Out of Stock: <b>{out_of_stock}</b> (🔴)\n"
        f"• Actively Monitored by You: <b>{user_tracked_count}</b>\n\n"
        "⚡ <b>Fast Restock Loop:</b> Checking StoreHippo every 60s with instant alerts."
    )


def format_amul_product_count(products: List[dict]) -> str:
    """Format inventory quantities table for products."""
    sorted_prods = sorted(products, key=lambda p: p.get("inventory_quantity", 0), reverse=True)
    lines = ["📦 <b>Amul Available Product Counts</b>\n"]
    for i, p in enumerate(sorted_prods, 1):
        name = p.get("name", "Product")
        qty = p.get("inventory_quantity", 0)
        status_dot = "🟢" if qty > 0 else "🔴"
        lines.append(f"{i}. <b>{name}</b>: {status_dot} <b>{qty} units</b>")
    return "\n".join(lines)


def format_settings_menu(user: User) -> str:
    """Format user preferences and alert settings overview."""
    style_label = "Always 🔄" if user.tracking_style == "always" else "Once 1️⃣"
    ao_label = "Enabled 🟢" if user.auto_order_enabled else "Disabled ⚪"
    all_protein_active = "ALL_PROTEIN" in (user.favourite_skus or [])
    all_protein_label = "Active 🔔 (All Items)" if all_protein_active else "Inactive 🔕 (Tracked/Favs Only)"
    phone_label = user.auto_order_phone or "Not configured"
    repeat_label = "♾️ Until Stock Runs Out (Dynamic)" if user.max_notify_count == 0 else f"{user.max_notify_count} Dynamic Alerts"

    return (
        "⚙️ <b>Notification & Tracking Settings</b>\n\n"
        f"• <b>Default Pincode:</b> <code>{user.default_pincode or '842002'}</code> (use <code>/pincode</code> to change)\n"
        f"• <b>All-Protein Restock Alerts:</b> <b>{all_protein_label}</b>\n"
        f"• <b>Repeat Stock Alerts:</b> <b>{repeat_label}</b>\n"
        f"• <b>Tracking Style:</b> <b>{style_label}</b>\n"
        f"• <b>Auto-Order Checkout:</b> <b>{ao_label}</b> ({phone_label})\n\n"
        "<b>Options Guide:</b>\n"
        "• <b>Repeat Stock Alerts</b>: Sends dynamic updates when stock decreases or periodic reminders while in stock (1-10 or continuous until OOS).\n"
        "• <b>All-Protein Alerts</b>: Instant notification when ANY protein product restocks in your warehouse.\n"
        "• <b>Always</b>: Keeps tracking the product continuously across restock cycles.\n"
        "• <b>Once</b>: Alerts once on restock, then automatically untracks."
    )


def format_auto_order_overview(user: User, addresses: Optional[List[dict]] = None) -> str:
    """Format Auto-Order status, linked mobile, and delivery addresses."""
    status_icon = "🟢 ACTIVE" if user.auto_order_enabled else "⚪ INACTIVE"
    phone_text = user.auto_order_phone or "None (send <code>/autoorder login &lt;phone&gt;</code>)"
    skus_text = ", ".join(user.auto_order_skus) if user.auto_order_skus else "None"
    addr_text = user.auto_order_address_id or "Default Primary Warehouse Address"

    lines = [
        f"⚡ <b>Amul Headless Auto-Order Engine</b> [{status_icon}]\n",
        f"📱 <b>Linked Mobile:</b> <code>{phone_text}</code>",
        f"📍 <b>Delivery Address ID:</b> <code>{addr_text}</code>",
        f"📦 <b>Auto-Order SKUs:</b> <code>{skus_text}</code>\n",
        "<b>How Auto-Order Works:</b>",
        "1. When Amul restocks your chosen SKU, PriceWatch detects it within 60 seconds.",
        "2. The bot automatically creates a cart session and triggers StoreHippo COD checkout.",
        "3. You receive an instant Telegram message with your order confirmation ID!\n",
        "<b>Commands:</b>",
        "• <code>/autoorder login &lt;10-digit-mobile&gt;</code> - Request Amul OTP",
        "• <code>/autoorder otp &lt;6-digit-code&gt;</code> - Verify OTP & save session",
        "• <code>/autoorder toggle</code> - Enable or disable auto-ordering",
        "• <code>/autoorder add &lt;sku&gt;</code> - Add SKU to auto-order list",
        "• <code>/autoorder remove &lt;sku&gt;</code> - Remove SKU from auto-order list",
    ]
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
