"""Unit tests for AmulProvider (StoreHippo API and inventory logic)."""

import pytest
import respx
import httpx
from pricewatch.providers.amul import AmulProvider, SHOP_URL


def test_amul_can_handle():
    assert AmulProvider.can_handle("https://shop.amul.com/en/browse/protein")
    assert AmulProvider.can_handle("https://shop.amul.com/en/browse/product/amul-high-protein-blueberry-shake-200-ml-or-pack-of-30")
    assert AmulProvider.can_handle("https://amul.com/some/path")
    assert not AmulProvider.can_handle("https://amazon.in/dp/B07WZM3714")
    assert not AmulProvider.can_handle("https://nakpro.com/products/whey")


def test_calculate_tid_header():
    session_tid = "test-session-tid-12345"
    header_val = AmulProvider.calculate_tid_header(session_tid)
    parts = header_val.split(":")
    assert len(parts) == 3
    assert len(parts[0]) > 0
    assert len(parts[1]) > 0
    assert len(parts[2]) == 64


def test_calculate_effective_inventory():
    provider = AmulProvider()

    # Case 1: normal available with inventory
    item_in_stock = {
        "available": 1,
        "inventory_quantity": 45,
        "inventory_low_stock_quantity": 5,
        "inventory_allow_out_of_stock": 0,
    }
    avail, qty = provider.calculate_effective_inventory(item_in_stock)
    assert avail is True
    assert qty == 40

    # Case 2: available 0 / False
    item_oos = {
        "available": 0,
        "inventory_quantity": 50,
        "inventory_low_stock_quantity": 0,
    }
    avail, qty = provider.calculate_effective_inventory(item_oos)
    assert avail is False
    assert qty == 0

    # Case 3: inventory <= low_stock
    item_low = {
        "available": 1,
        "inventory_quantity": 4,
        "inventory_low_stock_quantity": 5,
        "inventory_allow_out_of_stock": 0,
    }
    avail, qty = provider.calculate_effective_inventory(item_low)
    assert avail is False
    assert qty == 0

    # Case 4: allow out of stock overrides
    item_backorder = {
        "available": 1,
        "inventory_quantity": 0,
        "inventory_low_stock_quantity": 0,
        "inventory_allow_out_of_stock": 1,
    }
    avail, qty = provider.calculate_effective_inventory(item_backorder)
    assert avail is True
    assert qty == 999


@pytest.mark.asyncio
@respx.mock
async def test_resolve_substore_for_pincode():
    provider = AmulProvider()
    provider._session_tid = "mock_tid"
    provider._session_created_at = 9999999999

    respx.get(url__startswith=f"{SHOP_URL}/entity/pincode").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"substore": "delhi", "pincode": "110001"}]},
        )
    )

    substore = await provider.resolve_substore_for_pincode("110001")
    assert substore == "delhi"
    # Cached call
    cached = await provider.resolve_substore_for_pincode("110001")
    assert cached == "delhi"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_quote_mocked():
    provider = AmulProvider()
    provider._session_tid = "mock_tid"
    provider._session_created_at = 9999999999

    respx.get(url__startswith=f"{SHOP_URL}/entity/pincode").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"substore": "delhi", "pincode": "110001"}]},
        )
    )
    respx.put(f"{SHOP_URL}/entity/ms.settings/_/setPreferences").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(url__startswith=f"{SHOP_URL}/api/1/entity/ms.products").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": "Amul High Protein Buttermilk",
                        "sku": "AMUL-PROT-BM-30",
                        "price": 25,
                        "compare_price": 30,
                        "available": 1,
                        "inventory_quantity": 100,
                        "inventory_low_stock_quantity": 5,
                        "inventory_allow_out_of_stock": 0,
                    }
                ]
            },
        )
    )

    quote = await provider.fetch_quote(
        canonical_url="https://shop.amul.com/en/product/AMUL-PROT-BM-30",
        external_product_id="AMUL-PROT-BM-30",
        external_variant_id="AMUL-PROT-BM-30",
        pincode="110001",
    )

    assert quote.available is True
    assert quote.price_paise == 2500
    assert quote.mrp_paise == 3000
    assert quote.inventory_quantity == 95
    assert "Buttermilk" in quote.raw_variant_title
