"""Telegram Inline Keyboard builders."""

from __future__ import annotations

from typing import List, Optional, Sequence, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pricewatch.domain.models import CanonicalListing, User, VariantOption
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

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel")])
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
        ],
    ])



def build_untrack_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for removing a tracked listing."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, Untrack", callback_data=f"del:confirm:{listing_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="del:cancel"),
        ]
    ])


def build_tracking_mode_keyboard(
    listing_id: int,
    current_price_paise: int,
    is_in_stock: bool = True,
) -> InlineKeyboardMarkup:
    """Combined intuitive tracking options: Combined Auto-Tracker (Stock & Discounts) or Custom Target."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Auto-Track (Stock & Discounts)", callback_data=f"trk_mode:{listing_id}:auto"),
        ],
        [
            InlineKeyboardButton("🎯 Set Custom Target Price", callback_data=f"trk_mode:{listing_id}:target"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
        ],
    ])


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
            InlineKeyboardButton("⬅️ Back to Tracking Options", callback_data=f"trk_mode:{listing_id}:back"),
            InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel"),
        ],
    ])


def build_listing_card_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """Action buttons for tracked listings (Chart + Untrack)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 View Price Chart", callback_data=f"chart:{listing_id}"),
            InlineKeyboardButton("🗑️ Untrack", callback_data=f"del:confirm:{listing_id}"),
        ]
    ])


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
        InlineKeyboardButton("⬅️ Back to Menu", callback_data="amul_menu"),
        InlineKeyboardButton("⚙️ Settings", callback_data="cfg:refresh"),
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
    ])


def build_action_nav_keyboard(
    btn1_text: str, btn1_cb: str, btn2_text: Optional[str] = None, btn2_cb: Optional[str] = None
) -> InlineKeyboardMarkup:
    """Generic 1-2 button navigation bar for confirmation/action messages."""
    row = [InlineKeyboardButton(btn1_text, callback_data=btn1_cb)]
    if btn2_text and btn2_cb:
        row.append(InlineKeyboardButton(btn2_text, callback_data=btn2_cb))
    return InlineKeyboardMarkup([row])


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

    keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data="amul_menu")])
    return InlineKeyboardMarkup(keyboard)

