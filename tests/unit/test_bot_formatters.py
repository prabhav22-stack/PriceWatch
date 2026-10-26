"""Unit tests for Telegram message formatters."""

from pricewatch.bot.formatters import (
    format_help_message,
    format_subscription_list,
    format_tracking_confirmation,
    format_welcome_message,
)
from pricewatch.domain.models import CanonicalListing, Subscription


def test_welcome_formatter():
    msg = format_welcome_message("Prabhav")
    assert "Prabhav" in msg
    assert "/track" in msg


def test_help_formatter():
    msg = format_help_message()
    assert "/track" in msg
    assert "/list" in msg
    assert "/untrack" in msg


def test_tracking_confirmation_formatter():
    listing = CanonicalListing(
        id=99,
        provider_code="shopify:nakpro.com",
        external_product_id="whey",
        external_variant_id="v1",
        canonical_url="https://nakpro.com/whey",
        product_title="Nakpro Whey",
        variant_title="1 kg / Chocolate",
        last_price_paise=134900,
        last_mrp_paise=199900,
    )
    sub = Subscription(
        id=1,
        telegram_id=123,
        listing_id=99,
        target_price_paise=120000,
    )
    text = format_tracking_confirmation(listing, sub)
    assert "Nakpro Whey" in text
    assert "1 kg / Chocolate" in text
    assert "₹1,349" in text
    assert "₹1,200" in text
    assert "<b>Listing ID:</b> <code>99</code>" in text


def test_subscription_list_empty():
    text = format_subscription_list([])
    assert "no active tracked products" in text


def test_subscription_list_with_items():
    listing = CanonicalListing(
        id=99,
        provider_code="shopify:nakpro.com",
        external_product_id="whey",
        external_variant_id="v1",
        canonical_url="https://nakpro.com/whey",
        product_title="Nakpro Whey",
        variant_title="1 kg / Chocolate",
        last_price_paise=134900,
        last_available=True,
    )
    sub = Subscription(
        id=1,
        telegram_id=123,
        listing_id=99,
        target_price_paise=120000,
    )
    text = format_subscription_list([(sub, listing)])
    assert "Your Tracked Products (1)" in text
    assert "Nakpro Whey" in text
    assert "/untrack_99" in text
