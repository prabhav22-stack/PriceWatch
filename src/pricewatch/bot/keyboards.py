"""Telegram Inline Keyboard builders."""

from typing import List, Sequence, Set
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
    """Settings interactive controls for style, max notifications, and auto-order."""
    style_toggle = "Once 1️⃣" if user.tracking_style == "always" else "Always 🔄"
    ao_toggle = "Disable ⚪" if user.auto_order_enabled else "Enable 🟢"
    all_protein_toggle = "Turn Off 🔕" if "ALL_PROTEIN" in (user.favourite_skus or []) else "Turn On 🔔"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"All Protein Alerts: {all_protein_toggle}", callback_data="cfg:toggle_all_protein"),
        ],
        [
            InlineKeyboardButton(f"Switch Tracking to: {style_toggle}", callback_data="cfg:toggle_style"),
        ],
        [
            InlineKeyboardButton("Max: 1 Alert", callback_data="cfg:max:1"),
            InlineKeyboardButton("Max: 3 Alerts", callback_data="cfg:max:3"),
            InlineKeyboardButton("Max: 5 Alerts", callback_data="cfg:max:5"),
        ],
        [
            InlineKeyboardButton(f"Auto-Order: {ao_toggle}", callback_data="cfg:toggle_ao"),
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


def build_amul_category_keyboard() -> InlineKeyboardMarkup:
    """Categories menu for Amul Shop stock browser."""
    from pricewatch.providers.amul import AMUL_CATEGORIES
    buttons: List[InlineKeyboardButton] = [
        InlineKeyboardButton(f"{c['emoji']} {c['label']}", callback_data=f"amul_cat:{c['id']}")
        for c in AMUL_CATEGORIES
    ]
    # 2 columns layout
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
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

    keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data="amul_menu")])
    return InlineKeyboardMarkup(keyboard)


def build_settings_keyboard(user: User) -> InlineKeyboardMarkup:
    """Settings interactive controls for style, max notifications, and auto-order."""
    style_toggle = "Once 1️⃣" if user.tracking_style == "always" else "Always 🔄"
    ao_toggle = "Disable ⚪" if user.auto_order_enabled else "Enable 🟢"
    all_protein_toggle = "Turn Off 🔕" if "ALL_PROTEIN" in (user.favourite_skus or []) else "Turn On 🔔"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"All Protein Alerts: {all_protein_toggle}", callback_data="cfg:toggle_all_protein"),
        ],
        [
            InlineKeyboardButton(f"Switch Tracking to: {style_toggle}", callback_data="cfg:toggle_style"),
        ],
        [
            InlineKeyboardButton("Max: 1 Alert", callback_data="cfg:max:1"),
            InlineKeyboardButton("Max: 3 Alerts", callback_data="cfg:max:3"),
            InlineKeyboardButton("Max: 5 Alerts", callback_data="cfg:max:5"),
        ],
        [
            InlineKeyboardButton(f"Auto-Order: {ao_toggle}", callback_data="cfg:toggle_ao"),
        ],
    ])

