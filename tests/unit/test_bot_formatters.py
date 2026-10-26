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


def test_stepwise_product_preview_formatter():
    from pricewatch.bot.formatters import format_stepwise_product_preview
    listing = CanonicalListing(
        id=55,
        provider_code="amazon",
        external_product_id="B002",
        external_variant_id="B002",
        canonical_url="https://amazon.in/dp/B002",
        product_title="Isolate Whey",
        variant_title="Vanilla 1kg",
        last_price_paise=300000,
        last_mrp_paise=350000,
        last_available=True,
        pincode="110001",
    )
    preview = format_stepwise_product_preview(listing)
    assert "Isolate Whey" in preview
    assert "Vanilla 1kg" in preview
    assert "₹3,000" in preview
    assert "₹3,500" in preview
    assert "What target price would you like to set" in preview


def test_amul_formatters():
    from pricewatch.bot.formatters import format_amul_category_view, format_amul_tracking_confirmed
    products = [
        {"name": "Amul Protein Lassi", "sku": "lassi-01", "price_paise": 2500, "available": True, "inventory_quantity": 40},
        {"name": "Amul Protein Shake", "sku": "shake-02", "price_paise": 4000, "available": False, "inventory_quantity": 0},
    ]
    view = format_amul_category_view("Protein", "110001", "delhi", products)
    assert "Amul Protein Products" in view
    assert "40 units" in view
    assert "Out of Stock" in view

    conf = format_amul_tracking_confirmed("Amul Protein Lassi", "lassi-01", "110001", True, 40)
    assert "Amul Stock Tracker Activated" in conf
    assert "lassi-01" in conf
    assert "40 units" in conf


def test_amul_category_messages_and_rendering():
    from pricewatch.bot.formatters import (
        format_amul_category_menu,
        format_amul_category_messages,
        render_amul_product_item,
    )
    menu = format_amul_category_menu("842002", "bihar")
    assert "Amul Products" in menu
    assert "(842002 - bihar)" in menu

    product = {
        "name": "Amul High Protein Buttermilk, 200 mL | Pack of 30",
        "sku": "BTMCP11_30",
        "price_paise": 79900,
        "available": True,
        "inventory_quantity": 723,
        "protein": "15g protein",
    }
    rendered = render_amul_product_item(product, 1, is_tracked=False, bot_username="wheypricewatch_bot")
    assert "1. <b><a href=" in rendered
    assert "Protein: <b>15g protein</b>" in rendered
    assert "Price: <b>799₹</b>" in rendered
    assert "In Stock: <b>Yes 🟢</b>" in rendered
    assert "Available Quantity: <b>723</b>" in rendered
    assert "[Track]" in rendered
    assert "start=track_BTMCP11_30" in rendered

    msgs = format_amul_category_messages(
        category_label="Protein",
        category_emoji="💪",
        pincode="842002",
        substore="bihar",
        products=[product] * 5,
        tracked_skus={"BTMCP11_30"},
        bot_username="wheypricewatch_bot",
    )
    assert len(msgs) >= 1
    assert "Amul 💪 Protein Products" in msgs[0]
    assert "(842002 - bihar)" in msgs[0]
    assert "[Untrack]" in msgs[0]


