"""Unit tests for AmulStockTracker and product formatting with stock history."""

from datetime import datetime, timezone, timedelta
from pricewatch.bot.formatters import render_amul_product_item
from pricewatch.services.amul_stock_tracker import AmulStockTracker, AmulStockHistoryItem


def test_amul_stock_tracker_transitions():
    tracker = AmulStockTracker(supabase_client=None)
    sku = "TEST_SKU_1"
    substore = "bihar"

    now = datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc)
    # 1. Product is observed In Stock
    item = tracker.record_observation(sku, substore, is_available=True, observed_at=now)
    assert item.last_seen_in_stock_at == now
    assert item.first_seen_in_stock_at == now
    assert item.last_seen_out_of_stock_at is None

    # 2. 2 hours later, product is still in stock
    now_later = now + timedelta(hours=2)
    item2 = tracker.record_observation(sku, substore, is_available=True, observed_at=now_later)
    assert item2.last_seen_in_stock_at == now_later
    assert item2.first_seen_in_stock_at == now  # Kept original first seen
    assert item2.last_seen_out_of_stock_at is None

    # 3. 3 hours later, product goes out of stock
    oos_time = now + timedelta(hours=3)
    item3 = tracker.record_observation(sku, substore, is_available=False, observed_at=oos_time)
    assert item3.last_seen_in_stock_at == now_later
    assert item3.first_seen_in_stock_at == now
    assert item3.last_seen_out_of_stock_at == oos_time


def test_render_amul_product_item_url_and_stock_history():
    now = datetime(2026, 10, 26, 10, 53, 0, tzinfo=timezone.utc)
    oos = now - timedelta(days=2)
    first_in = oos - timedelta(days=1)

    product = {
        "sku": "BTMCP11_30",
        "alias": "amul-high-protein-buttermilk-200-ml-or-pack-of-30",
        "name": "Amul High Protein Buttermilk, 200 mL | Pack of 30",
        "price_paise": 79900,
        "available": True,
        "inventory_quantity": 723,
        "protein": "15g protein",
    }

    history = AmulStockHistoryItem(
        sku="BTMCP11_30",
        substore="bihar",
        last_seen_in_stock_at=now,
        first_seen_in_stock_at=first_in,
        last_seen_out_of_stock_at=oos,
    )

    rendered = render_amul_product_item(
        product=product,
        index=1,
        is_tracked=False,
        stock_history=history,
    )

    # 1. Verify link points directly to /en/product/<alias> (without browse/ and without spaces)
    assert 'href="https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30"' in rendered

    # 2. Verify In Stock: Yes 🟢
    assert "In Stock: <b>Yes 🟢</b>" in rendered

    # 3. Verify stock history lines
    assert "Last InStock:" in rendered
    assert "Last Out of Stock:" in rendered
    assert "In Stock Duration:" in rendered
    assert "Available Quantity: <b>723</b>" in rendered
    assert "[Track]" in rendered
    assert "[Favourite]" in rendered
