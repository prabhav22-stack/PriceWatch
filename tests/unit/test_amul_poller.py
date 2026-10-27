"""Unit tests for background Amul 60s poller."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import respx
import httpx

from pricewatch.domain.enums import AlertType
from pricewatch.domain.models import CanonicalListing, PriceQuote, Subscription, User
from pricewatch.providers.amul import SHOP_URL
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.amul_poller import run_amul_poller


@pytest.mark.asyncio
@respx.mock
async def test_run_amul_poller_detects_restock_and_alerts():
    repo = MemoryRepository()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    # Create Amul listing (currently out of stock)
    listing = CanonicalListing(
        provider_code="amul",
        provider_tier=1,
        external_product_id="SKU-BUTTERMILK-30",
        external_variant_id="SKU-BUTTERMILK-30",
        pincode="110001",
        canonical_url="https://shop.amul.com/en/browse/product/SKU-BUTTERMILK-30",
        product_title="Amul High Protein Buttermilk",
        variant_title="Standard Pack",
        currency="INR",
        last_price_paise=2500,
        last_available=False,
        is_monitored=True,
    )
    saved_listing = await repo.get_or_create_listing(listing)

    # User subscription with alert_rearmed=True
    sub = Subscription(
        telegram_id=98765,
        listing_id=saved_listing.id,
        target_price_paise=2500,
        notify_on_restock=True,
        is_active=True,
        alert_rearmed=True,
    )
    await repo.create_or_update_subscription(sub)

    # Mock Amul API returning restocked item
    respx.get(url__startswith=f"{SHOP_URL}/entity/pincode").mock(
        return_value=httpx.Response(200, json={"records": [{"substore": "delhi", "pincode": "110001"}]})
    )
    respx.put(f"{SHOP_URL}/entity/ms.settings/_/setPreferences").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(f"{SHOP_URL}/en/browse/protein").mock(return_value=httpx.Response(200, text="ok"))
    respx.get(url__startswith=f"{SHOP_URL}/user/info.js").mock(
        return_value=httpx.Response(200, text='session = {"tid": "test_tid"};')
    )
    respx.get(url__startswith=f"{SHOP_URL}/api/1/entity/ms.products").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": "Amul High Protein Buttermilk",
                        "sku": "SKU-BUTTERMILK-30",
                        "price": 25,
                        "compare_price": 30,
                        "available": 1,
                        "inventory_quantity": 80,
                        "inventory_low_stock_quantity": 5,
                        "inventory_allow_out_of_stock": 0,
                    }
                ]
            },
        )
    )

    # Start poller task with interval 0.1s
    task = asyncio.create_task(run_amul_poller(repo=repo, bot=bot, interval_seconds=1))

    # Give it a brief moment to run first cycle
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Verify bot sent restock alert!
    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args[1]["chat_id"] == 98765
    msg_text = call_args[1]["text"]
    assert "AMUL PRODUCT BACK IN STOCK" in msg_text
    assert "75 units" in msg_text
    assert "Amul High Protein Buttermilk" in msg_text


@pytest.mark.asyncio
@respx.mock
async def test_run_amul_poller_batch_updates_subscribed_items():
    repo = MemoryRepository()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    # Explicit user subscription
    user = User(
        telegram_id=12345,
        default_pincode="842002",
    )
    repo.users[12345] = user

    listing = CanonicalListing(
        id=1,
        provider_code="amul",
        external_product_id="BTMCP11_30",
        external_variant_id="BTMCP11_30",
        pincode="842002",
        canonical_url="https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30",
        product_title="Amul High Protein Buttermilk, 200 mL | Pack of 30",
        last_price_paise=79900,
        last_available=False,
    )
    repo.listings[1] = listing

    sub = Subscription(
        id=1,
        telegram_id=12345,
        listing_id=1,
        target_price_paise=79900,
        notify_on_restock=True,
        is_active=True,
        alert_rearmed=True,
    )
    repo.subscriptions[1] = sub

    # Mock Amul API
    respx.get(url__startswith=f"{SHOP_URL}/entity/pincode").mock(
        return_value=httpx.Response(200, json={"records": [{"substore": "bihar", "pincode": "842002"}]})
    )
    respx.put(f"{SHOP_URL}/entity/ms.settings/_/setPreferences").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(f"{SHOP_URL}/en/browse/protein").mock(return_value=httpx.Response(200, text="ok"))
    respx.get(url__startswith=f"{SHOP_URL}/user/info.js").mock(
        return_value=httpx.Response(200, text='session = {"tid": "test_tid"};')
    )
    respx.get(url__startswith=f"{SHOP_URL}/api/1/entity/ms.products").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": "Amul High Protein Buttermilk, 200 mL | Pack of 30",
                        "sku": "BTMCP11_30",
                        "price": 799,
                        "available": 1,
                        "inventory_quantity": 469,
                        "inventory_low_stock_quantity": 10,
                    }
                ]
            },
        )
    )

    task = asyncio.create_task(run_amul_poller(repo=repo, bot=bot, interval_seconds=1))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Verify user received restock alert automatically!
    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args[1]["chat_id"] == 12345
    msg = call_args[1]["text"]
    assert "AMUL PRODUCT BACK IN STOCK" in msg
    assert "BTMCP11_30" in msg or "Buttermilk" in msg


@pytest.mark.asyncio
async def test_alert_service_dynamic_stock_decrease_alert():
    from pricewatch.services.alert_service import AlertService

    repo = MemoryRepository()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    # User configured with 3 repeat alerts
    user = User(
        telegram_id=55555,
        default_pincode="842002",
        max_notify_count=3,
    )
    repo.users[55555] = user

    listing = CanonicalListing(
        id=1,
        provider_code="amul",
        external_product_id="BTMCP11_30",
        external_variant_id="BTMCP11_30",
        pincode="842002",
        canonical_url="https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30",
        product_title="Amul High Protein Buttermilk, 200 mL | Pack of 30",
        last_price_paise=79900,
        last_available=True,
    )
    repo.listings[1] = listing

    sub = Subscription(
        id=10,
        telegram_id=55555,
        listing_id=1,
        target_price_paise=79900,
        notify_on_restock=True,
        is_active=True,
        alert_rearmed=False,
        last_alerted_price_paise=458,  # Previously alerted at 458 units
    )
    repo.subscriptions[10] = sub

    alert_service = AlertService(subscription_repo=repo, user_repo=repo, bot=bot)
    alert_service._cycle_counts[10] = 1

    # Stock drops from 458 -> 410
    decreased_quote = PriceQuote(
        external_product_id="BTMCP11_30",
        external_variant_id="BTMCP11_30",
        price_paise=79900,
        available=True,
        inventory_quantity=410,
        currency="INR",
        verified_pincode="842002",
        extraction_method="test",
    )

    sent = await alert_service.process_quote(listing, decreased_quote)
    assert sent == 1
    bot.send_message.assert_called_once()
    args = bot.send_message.call_args[1]
    assert args["chat_id"] == 55555
    text = args["text"]
    assert "AMUL STOCK DECREASING" in text
    assert "458" in text and "410" in text
    # Verify inline button links to exact product URL
    kb = args["reply_markup"]
    assert kb.inline_keyboard[0][0].url == "https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30"
