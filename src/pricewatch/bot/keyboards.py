"""Telegram Inline Keyboard builders."""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from pricewatch.domain.models import CanonicalListing, ComparisonResult, StoreDeal, User, VariantOption
from pricewatch.validation.normalizer import format_paise_to_inr


def build_variant_selection_keyboard(
    variants: Sequence[VariantOption],
    target_price_paise: int,
) -> InlineKeyboardMarkup:
    """Build inline buttons for each variant option."""
    keyboard: List[List[InlineKeyboardButton]] = []

    for v in variants:
        price_text = format_paise_to_inr(v.price_paise) if v.price_paise else "N/A"
        avail_text = "" if v.available else " (OOS)"
        button_text = f"{v.variant_title} - {price_text}{avail_text}"

        callback_data = f"trk:v:{v.external_variant_id}:{target_price_paise}"
        if len(callback_data.encode("utf-8")) > 64:
            callback_data = f"trk:v:{v.external_variant_id}"

        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(keyboard)


def build_settings_keyboard(user: User) -> InlineKeyboardMarkup:
    """Settings interactive controls with active checkmark feedback."""
    r_val = user.max_notify_count

    btn_1 = "✅ 1x" if r_val == 1 else "1 Alert"
    btn_2 = "✅ 2x" if r_val == 2 else "2 Alerts"
    btn_3 = "✅ 3x" if r_val == 3 else "3 Alerts"
    btn_5 = "✅ 5x" if r_val == 5 else "5 Alerts"
    btn_10 = "✅ 10x" if r_val == 10 else "10 Alerts"
    btn_0 = "✅ ♾️ Until OOS" if r_val == 0 else "♾️ Until OOS"

    style_always = "✅ Always 🔄" if user.tracking_style == "always" else "Always 🔄"
    style_once = "✅ Once 1️⃣" if user.tracking_style == "once" else "Once 1️⃣"

    all_protein_on = "ALL_PROTEIN" in (user.favourite_skus or [])
    btn_ap = "🔔 All-Protein Alerts: ON" if all_protein_on else "🔕 All-Protein Alerts: OFF"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(btn_ap, callback_data="cfg:toggle_all_protein"),
        ],
        [
            InlineKeyboardButton(btn_1, callback_data="cfg:repeat:1"),
            InlineKeyboardButton(btn_2, callback_data="cfg:repeat:2"),
            InlineKeyboardButton(btn_3, callback_data="cfg:repeat:3"),
        ],
        [
            InlineKeyboardButton(btn_5, callback_data="cfg:repeat:5"),
            InlineKeyboardButton(btn_10, callback_data="cfg:repeat:10"),
            InlineKeyboardButton(btn_0, callback_data="cfg:repeat:0"),
        ],
        [
            InlineKeyboardButton(style_always, callback_data="cfg:style:always"),
            InlineKeyboardButton(style_once, callback_data="cfg:style:once"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Status", callback_data="cfg:refresh"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ],
    ])


def build_untrack_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for removing a tracked listing."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, Untrack", callback_data=f"del:confirm:{listing_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="del:cancel"),
        ],
        [
            InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ],
    ])


def build_tracking_mode_keyboard(
    listing_id: int,
    current_price_paise: int,
    is_in_stock: bool = True,
    is_nutrabay: bool = False,
) -> InlineKeyboardMarkup:
    """Combined intuitive tracking options: Combined Auto-Tracker (Stock & Discounts) or Custom Target."""
    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("⚡ Auto-Track (Stock & Discounts)", callback_data=f"trk_mode:{listing_id}:auto"),
        ],
        [
            InlineKeyboardButton("🎯 Set Custom Target Price", callback_data=f"trk_mode:{listing_id}:target"),
        ],
        [
            InlineKeyboardButton("⚡ Check Live Stock", callback_data=f"stk:{listing_id}"),
            InlineKeyboardButton("🔍 Compare Stores", callback_data=f"cmp:{listing_id}"),
        ],
    ]
    if is_nutrabay:
        rows.append([
            InlineKeyboardButton("🕒 Last in Stock Report", callback_data=f"nb_stock:{listing_id}"),
        ])
    rows.append([
        InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(rows)


def build_target_price_keyboard(listing_id: int, current_price_paise: int) -> InlineKeyboardMarkup:
    """Dynamic quick-select price discount pills for stepwise onboarding."""
    c_p = current_price_paise
    m5 = int(round(c_p * 0.95))
    m10 = int(round(c_p * 0.90))
    m15 = int(round(c_p * 0.85))
    m20 = int(round(c_p * 0.80))

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🎯 Current ({format_paise_to_inr(c_p)})", callback_data=f"tgt:{listing_id}:{c_p}"),
            InlineKeyboardButton(f"📉 -5% ({format_paise_to_inr(m5)})", callback_data=f"tgt:{listing_id}:{m5}"),
        ],
        [
            InlineKeyboardButton(f"📉 -10% ({format_paise_to_inr(m10)})", callback_data=f"tgt:{listing_id}:{m10}"),
            InlineKeyboardButton(f"📉 -15% ({format_paise_to_inr(m15)})", callback_data=f"tgt:{listing_id}:{m15}"),
        ],
        [
            InlineKeyboardButton(f"📉 -20% ({format_paise_to_inr(m20)})", callback_data=f"tgt:{listing_id}:{m20}"),
            InlineKeyboardButton("✏️ Custom Price", callback_data=f"tgt_custom:{listing_id}"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Modes", callback_data=f"trk_mode:{listing_id}:back"),
            InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
        ],
    ])


def build_listing_card_keyboard(listing_id: int, is_nutrabay: bool = False) -> InlineKeyboardMarkup:
    """Action buttons for tracked listings (Chart + WebApp + Untrack + Menu)."""
    rows = [
        [
            InlineKeyboardButton("📊 View Price Chart", callback_data=f"chart:{listing_id}"),
            InlineKeyboardButton("🗑️ Untrack", callback_data=f"del:confirm:{listing_id}"),
        ],
        [
            InlineKeyboardButton("⚡ Check Live Stock", callback_data=f"stk:{listing_id}"),
            InlineKeyboardButton("🔍 Compare Stores", callback_data=f"cmp:{listing_id}"),
        ],
    ]
    webapp_url = os.getenv("WEBAPP_URL")
    if webapp_url:
        rows.append([
            InlineKeyboardButton(
                "📱 Interactive Dashboard",
                web_app=WebAppInfo(url=f"{webapp_url.rstrip('/')}/webapp/dashboard/{listing_id}"),
            )
        ])
    if is_nutrabay:
        rows.append([
            InlineKeyboardButton("🕒 Last in Stock Report", callback_data=f"nb_stock:{listing_id}"),
        ])
    rows.append([
        InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(rows)


def build_comparison_keyboard(
    result: ComparisonResult,
    listing_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """Buttons for multi-store price comparison results."""
    rows: List[List[InlineKeyboardButton]] = []

    # Direct store links (top 5)
    top_deals = [d for d in result.deals if d.url][:5]
    for d in top_deals:
        p_str = format_paise_to_inr(d.price_paise) if d.price_paise else ""
        icon = "🟢" if d.available else "🔴"
        label = f"{icon} {d.store_name} ({p_str})"
        rows.append([InlineKeyboardButton(f"🛒 Open {label}", url=d.url)])

    action_row = []
    action_row.append(InlineKeyboardButton("📸 Visual Deal Card", callback_data=f"card:cmp:{listing_id or 0}"))
    if listing_id:
        action_row.append(InlineKeyboardButton("🔄 Refresh Deals", callback_data=f"cmp:{listing_id}"))
    action_row.append(InlineKeyboardButton("📋 Tracked", callback_data="nav:tracked"))
    action_row.append(InlineKeyboardButton("🏠 Menu", callback_data="nav:home"))
    rows.append(action_row)

    webapp_url = os.getenv("WEBAPP_URL")
    if webapp_url and listing_id:
        rows.append([
            InlineKeyboardButton(
                "📱 Interactive Dashboard",
                web_app=WebAppInfo(url=f"{webapp_url.rstrip('/')}/webapp/dashboard/{listing_id}"),
            )
        ])

    return InlineKeyboardMarkup(rows)


def build_instock_keyboard(
    result: ComparisonResult,
) -> InlineKeyboardMarkup:
    """Buttons for instant in-stock search results."""
    rows: List[List[InlineKeyboardButton]] = []

    # Direct store purchase buttons for in-stock stores (up to top 5)
    in_stock_deals = [d for d in result.deals if d.available and d.url]
    for d in in_stock_deals[:5]:
        p_str = format_paise_to_inr(d.price_paise) if d.price_paise else ""
        label = f"🛒 Buy on {d.store_name} ({p_str})"
        rows.append([InlineKeyboardButton(label, url=d.url)])

    action_row = []
    # If out of stock, offer 1-click tracking or compare
    if not in_stock_deals and result.deals:
        action_row.append(InlineKeyboardButton("🔔 Track Restock Alert", callback_data="trk:start"))
    action_row.append(InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"))
    action_row.append(InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"))
    rows.append(action_row)

    return InlineKeyboardMarkup(rows)


def build_cross_store_alert_keyboard(
    listing_id: int,
    alternative: StoreDeal,
) -> InlineKeyboardMarkup:
    """Keyboard for cross-store alternative in-stock discovery alert."""
    alt_price = format_paise_to_inr(alternative.price_paise)
    rows = [
        [
            InlineKeyboardButton(f"🛒 Buy on {alternative.store_name} ({alt_price})", url=alternative.url),
        ],
        [
            InlineKeyboardButton(f"⚡ Switch Tracking to {alternative.store_name}", callback_data=f"sw_trk:{listing_id}"),
        ],
        [
            InlineKeyboardButton("🔍 View All Stores", callback_data=f"cmp:{listing_id}"),
            InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def build_welcome_keyboard() -> InlineKeyboardMarkup:
    """Home dashboard quick navigation buttons for /start."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🥛 Browse Amul Products", callback_data="amul_menu"),
            InlineKeyboardButton("⭐ Favourites", callback_data="nav:favs"),
        ],
        [
            InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"),
            InlineKeyboardButton("⚙️ Alert Settings", callback_data="cfg:refresh"),
        ],
        [
            InlineKeyboardButton("⚡ Run Live Check", callback_data="nav:live_check"),
            InlineKeyboardButton("📊 System Status", callback_data="nav:status"),
        ],
        [
            InlineKeyboardButton("🔍 Quick Search", callback_data="nav:search"),
            InlineKeyboardButton("📍 Delivery Pincode", callback_data="nav:pincode"),
        ],
    ])


def build_amul_category_keyboard(pincode: str = "842002") -> InlineKeyboardMarkup:
    """Categories menu for Amul Shop stock browser with intuitive action shortcuts."""
    from pricewatch.providers.amul import AMUL_CATEGORIES
    buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(f"{c['emoji']} {c['label']}", callback_data=f"amul_cat:{c['id']}")
        for c in AMUL_CATEGORIES
    ]
    # 2 columns layout
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([
        InlineKeyboardButton("⭐ My Favourites", callback_data="nav:favs"),
        InlineKeyboardButton("🔍 Search Amul", callback_data="nav:search"),
    ])
    rows.append([
        InlineKeyboardButton(f"📍 PIN: {pincode}", callback_data="nav:pincode"),
        InlineKeyboardButton("⚙️ Alert Settings", callback_data="cfg:refresh"),
    ])
    rows.append([
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(rows)


def build_category_navigation_keyboard(category_id: str = "protein") -> InlineKeyboardMarkup:
    """Bottom navigation bar placed on the final category message chunk."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Back to Categories", callback_data="amul_menu"),
            InlineKeyboardButton("⭐ My Favourites", callback_data="nav:favs"),
        ],
        [
            InlineKeyboardButton("🔍 Quick Search", callback_data="nav:search"),
            InlineKeyboardButton("⚙️ Alert Settings", callback_data="cfg:refresh"),
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ],
    ])


def build_pincode_keyboard(current_pin: str = "842002") -> InlineKeyboardMarkup:
    """Interactive delivery hub switcher for top warehouse regions."""
    hubs = [
        ("842002", "Muzaffarpur"),
        ("800001", "Patna"),
        ("110001", "Delhi"),
        ("400001", "Mumbai"),
        ("560001", "Bangalore"),
        ("700001", "Kolkata"),
    ]
    buttons = []
    for pin, city in hubs:
        active = "✅ " if pin == current_pin else ""
        buttons.append(InlineKeyboardButton(f"{active}📍 {city} ({pin})", callback_data=f"set_pin:{pin}"))

    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([
        InlineKeyboardButton(f"🥛 Browse Products for {current_pin}", callback_data="amul_menu"),
    ])
    rows.append([
        InlineKeyboardButton("🥛 Browse Amul", callback_data="amul_menu"),
        InlineKeyboardButton("⚙️ Settings", callback_data="cfg:refresh"),
    ])
    rows.append([
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(rows)


def build_repeat_keyboard(current_count: int = 0) -> InlineKeyboardMarkup:
    """Interactive keypad for configuring repeated stock alerts."""
    btn_1 = "✅ 1 Alert" if current_count == 1 else "1 Alert"
    btn_2 = "✅ 2 Alerts" if current_count == 2 else "2 Alerts"
    btn_3 = "✅ 3 Alerts" if current_count == 3 else "3 Alerts"
    btn_5 = "✅ 5 Alerts" if current_count == 5 else "5 Alerts"
    btn_10 = "✅ 10 Alerts" if current_count == 10 else "10 Alerts"
    btn_0 = "✅ ♾️ Until OOS" if current_count == 0 else "♾️ Until OOS"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(btn_1, callback_data="cfg:repeat:1"),
            InlineKeyboardButton(btn_2, callback_data="cfg:repeat:2"),
            InlineKeyboardButton(btn_3, callback_data="cfg:repeat:3"),
        ],
        [
            InlineKeyboardButton(btn_5, callback_data="cfg:repeat:5"),
            InlineKeyboardButton(btn_10, callback_data="cfg:repeat:10"),
            InlineKeyboardButton(btn_0, callback_data="cfg:repeat:0"),
        ],
        [
            InlineKeyboardButton("⚙️ Full Settings", callback_data="cfg:refresh"),
            InlineKeyboardButton("🥛 Browse Amul", callback_data="amul_menu"),
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ],
    ])


def build_search_suggestions_keyboard() -> InlineKeyboardMarkup:
    """1-click popular search keywords for instant Amul product lookups."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🫐 Blueberry Lassi", callback_data="quick_search:blueberry"),
            InlineKeyboardButton("🥛 High Protein Lassi", callback_data="quick_search:lassi"),
        ],
        [
            InlineKeyboardButton("💪 Whey Protein", callback_data="quick_search:whey"),
            InlineKeyboardButton("🍫 Chocolate Milkshake", callback_data="quick_search:chocolate"),
        ],
        [
            InlineKeyboardButton("☕ Coffee Protein", callback_data="quick_search:coffee"),
            InlineKeyboardButton("🍪 Protein Cookies", callback_data="quick_search:cookies"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Categories", callback_data="amul_menu"),
            InlineKeyboardButton("⭐ Favourites", callback_data="nav:favs"),
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ],
    ])


def build_action_nav_keyboard(
    btn1_text: str,
    btn1_cb: str,
    btn2_text: Optional[str] = None,
    btn2_cb: Optional[str] = None,
    include_home: bool = True,
) -> InlineKeyboardMarkup:
    """Generic 1-2 button navigation bar for confirmation/action messages with optional home/back button."""
    rows: List[List[InlineKeyboardButton]] = []
    row = [InlineKeyboardButton(btn1_text, callback_data=btn1_cb)]
    if btn2_text and btn2_cb:
        row.append(InlineKeyboardButton(btn2_text, callback_data=btn2_cb))
    rows.append(row)
    if include_home and btn1_cb not in ("nav:home", "nav:start") and btn2_cb not in ("nav:home", "nav:start"):
        rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home")])
    return InlineKeyboardMarkup(rows)


def build_amul_product_stock_keyboard(
    products: List[dict], tracked_skus: Set[str]
) -> InlineKeyboardMarkup:
    """Buttons to track stock for each Amul product in a category."""
    keyboard: List[List[InlineKeyboardButton]] = []
    for p in products[:12]:  # limit buttons per message
        sku = p.get("sku", "")
        name = p.get("name", "Product")
        trunc_name = (name[:28] + "..") if len(name) > 28 else name
        avail = p.get("available", False)
        qty = p.get("inventory_quantity", 0)

        icon = "🟢" if avail else "🔴"
        stock_text = f"({qty} units)" if avail else "(OOS)"

        if sku in tracked_skus:
            btn_text = f"✅ {trunc_name} {stock_text}"
            cb_data = f"amul_untrack:{sku}"
        else:
            btn_text = f"🔔 {trunc_name} {stock_text}"
            cb_data = f"amul_track:{sku}"

        keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])

    keyboard.append([
        InlineKeyboardButton("⬅️ Back to Categories", callback_data="amul_menu"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(keyboard)
