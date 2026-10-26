"""Telegram Inline Keyboard builders."""

from typing import List, Sequence
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pricewatch.domain.models import VariantOption
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

        # Callback data format: trk:v:<variant_id>:<target_price_paise>
        callback_data = f"trk:v:{v.external_variant_id}:{target_price_paise}"
        # Telegram callback_data limit is 64 bytes
        if len(callback_data.encode("utf-8")) > 64:
            callback_data = f"trk:v:{v.external_variant_id}"

        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="trk:cancel")])
    return InlineKeyboardMarkup(keyboard)


def build_untrack_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for removing a tracked listing."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, Untrack", callback_data=f"del:confirm:{listing_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="del:cancel"),
        ]
    ])
