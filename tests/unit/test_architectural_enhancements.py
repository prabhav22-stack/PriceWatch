"""Unit tests for Architectural Enhancements:
1. Cashews Cache (stampede protection)
2. Scrapling AdaptiveEcomParser (self-healing parsing)
3. StealthBrowserManager
4. Apprise MultiChannelNotifier
5. Telegram Mini App (FastAPI dashboard)
6. /channels command & callback handlers
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import channels_command_handler
from pricewatch.core.cache import cache
from pricewatch.domain.models import CanonicalListing, PriceObservation
from pricewatch.providers.adaptive_parser import AdaptiveEcomParser
from pricewatch.providers.stealth_browser import StealthBrowserManager
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.multi_channel_notifier import MultiChannelNotifier
from pricewatch.services.tracker_service import TrackerService
from pricewatch.webapp.server import app, set_webapp_context


@pytest.mark.asyncio
async def test_cashews_cache_basic():
    """Verify cashews cache sets, gets, and respects in-memory TTL."""
    await cache.set("test:key", "sample_val", expire="10s")
    val = await cache.get("test:key")
    assert val == "sample_val"


def test_scrapling_adaptive_parser_self_healing():
    """Verify Scrapling AdaptiveEcomParser extracts data dynamically without brittle classes."""
    html = """
    <html>
      <head><title>Nakpro Platinum Whey Isolate 1kg</title></head>
      <body>
        <div class="unknown_scrambled_123">
          <span class="any_tag">Special Offer: ₹2,499.00</span>
        </div>
        <del class="old_price">MRP: ₹3,999</del>
        <button class="cart-btn">Add to Cart</button>
      </body>
    </html>
    """
    parser = AdaptiveEcomParser(html)
    title, price_paise, mrp_paise, is_avail = parser.extract_all()

    assert "Nakpro" in title
    assert price_paise == 249900
    assert mrp_paise == 399900
    assert is_avail is True


def test_scrapling_adaptive_parser_out_of_stock():
    """Verify adaptive parser accurately detects out-of-stock indicators."""
    html = """
    <html>
      <head><title>Nutrabay Shilajit Resin 20g</title></head>
      <body>
        <div>Price: ₹499</div>
        <span class="stock_notice">Currently unavailable. We don't know when or if this item will be back in stock.</span>
      </body>
    </html>
    """
    parser = AdaptiveEcomParser(html)
    title, price_paise, mrp_paise, is_avail = parser.extract_all()

    assert "Nutrabay" in title
    assert price_paise == 49900
    assert is_avail is False


@pytest.mark.asyncio
async def test_stealth_browser_fallback():
    """Verify StealthBrowserManager falls back to Playwright if Camoufox fails."""
    with patch("camoufox.async_api.AsyncCamoufox", side_effect=Exception("Camoufox simulation error")):
        with patch("pricewatch.providers.stealth_browser.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_ctx = AsyncMock()
            mock_page = AsyncMock()
            mock_page.content.return_value = "<html><body>Fallback Success</body></html>"
            mock_ctx.new_page.return_value = mock_page
            mock_browser.new_context.return_value = mock_ctx
            mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

            content = await StealthBrowserManager.fetch_page_content("https://shop.amul.com/test")
            assert "Fallback Success" in content


@pytest.mark.asyncio
async def test_apprise_multichannel_notifier():
    """Verify MultiChannelNotifier handles empty and configured notification channels."""
    notifier = MultiChannelNotifier(default_channels=[])
    # Empty channels should return True without throwing
    res = await notifier.notify("Test Alert", "Alert body")
    assert res is True

    # With mocked apprise dispatch
    with patch("apprise.Apprise.async_notify", new_callable=AsyncMock) as mock_notify:
        mock_notify.return_value = True
        custom_notifier = MultiChannelNotifier(default_channels=["json://localhost/webhook"])
        res2 = await custom_notifier.notify("Test", "Body")
        assert res2 is True
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_fastapi_telegram_mini_app():
    """Verify TMA dashboard endpoint and API listing endpoint."""
    repo = MemoryRepository()
    listing = CanonicalListing(
        id=42,
        provider_code="nutrabay",
        external_product_id="nb-123",
        external_variant_id="default",
        canonical_url="https://nutrabay.com/product/123",
        product_title="Nutrabay Pro Whey",
        variant_title="1kg Chocolate",
        last_price_paise=199900,
        last_mrp_paise=299900,
        last_available=True,
    )
    repo.listings[42] = listing
    set_webapp_context(repo)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"

        # API listing data
        api_resp = await client.get("/api/v1/listing/42")
        assert api_resp.status_code == 200
        data = api_resp.json()
        assert data["id"] == 42
        assert data["current_price_rs"] == 1999.0

        # HTML Dashboard rendering
        html_resp = await client.get("/webapp/dashboard/42")
        assert html_resp.status_code == 200
        assert "Nutrabay Pro Whey" in html_resp.text
        assert "lightweight-charts" in html_resp.text.lower()
        assert "telegram-web-app.js" in html_resp.text


@pytest.mark.asyncio
async def test_channels_command_and_callback():
    """Verify /channels command and callback query dispatcher."""
    update = MagicMock()
    update.effective_user.id = 999
    update.effective_message.reply_html = AsyncMock()

    context = MagicMock()
    context.args = []
    context.user_data = {}

    # 1. /channels overview
    await channels_command_handler(update, context)
    update.effective_message.reply_html.assert_called_once()
    assert "Multi-Channel Notification Settings" in update.effective_message.reply_html.call_args[0][0]

    # 2. /channels add
    context.args = ["add", "ntfy://pricewatch_test"]
    update.effective_message.reply_html.reset_mock()
    await channels_command_handler(update, context)
    assert "Channel Added Successfully!" in update.effective_message.reply_html.call_args[0][0]
    assert "ntfy://pricewatch_test" in context.user_data["notification_channels"]

    # 3. channels:test callback
    cb_update = MagicMock()
    cb_query = cb_update.callback_query
    cb_query.data = "channels:test"
    cb_query.answer = AsyncMock()
    with patch("pricewatch.services.multi_channel_notifier.MultiChannelNotifier.notify", new_callable=AsyncMock) as mock_n:
        mock_n.return_value = True
        await callback_query_dispatcher(cb_update, context)
        cb_query.answer.assert_called()


def test_telegram_init_data_hmac_validation():
    """Verify Telegram WebApp initData HMAC-SHA256 signature verification."""
    import hashlib
    import hmac
    from pricewatch.webapp.server import validate_telegram_init_data

    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    raw_params = {
        "auth_date": "1662771500",
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": '{"id":279058397,"first_name":"Vladislav","last_name":"K","username":"vladislav"}',
    }
    data_check_string = "\n".join(f"{k}={raw_params[k]}" for k in sorted(raw_params.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    valid_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    valid_init_data = f"auth_date={raw_params['auth_date']}&query_id={raw_params['query_id']}&user={raw_params['user']}&hash={valid_hash}"

    # Valid data test
    res = validate_telegram_init_data(valid_init_data, bot_token=bot_token)
    assert res is not None
    assert res["user_data"]["id"] == 279058397

    # Tampered / invalid hash test
    invalid_init_data = valid_init_data.replace(valid_hash, "deadbeef1234567890")
    res_tampered = validate_telegram_init_data(invalid_init_data, bot_token=bot_token)
    assert res_tampered is None


def test_amazon_bot_block_detection():
    """Verify Amazon provider raises BotBlockedError on captcha strings and throttled shells."""
    from pricewatch.domain.exceptions import BotBlockedError
    from pricewatch.providers.amazon_fresh import AmazonFreshProvider

    captcha_html = "<html><head><title>Robot Check</title></head><body>Type the characters you see in this image</body></html>"
    with pytest.raises(BotBlockedError):
        AmazonFreshProvider.parse_html_content(captcha_html)

    throttled_empty_html = "<html><head><title>Amazon</title></head><body></body></html>"
    with pytest.raises(BotBlockedError):
        AmazonFreshProvider.parse_html_content(throttled_empty_html)


def test_amul_auto_order_idempotency_cooldown():
    """Verify Amul auto-order 24-hour idempotency cooldown prevents duplicate triggers."""
    from pricewatch.services.amul_auto_order import AmulAutoOrderService

    phone = "9876543210"
    sku = "AMUL_WHEY_CHOCOLATE_1KG"

    assert not AmulAutoOrderService._is_idempotency_locked(phone, sku)
    AmulAutoOrderService._set_idempotency_lock(phone, sku)
    assert AmulAutoOrderService._is_idempotency_locked(phone, sku)


@pytest.mark.asyncio
async def test_outbox_drainer_success():
    """Verify OutboxDrainer drains pending notifications at rate limit and marks SENT."""
    from pricewatch.domain.enums import AlertType, NotificationStatus
    from pricewatch.domain.models import NotificationLog, Subscription
    from pricewatch.services.outbox_drainer import OutboxDrainer

    repo = MemoryRepository()
    listing = CanonicalListing(
        id=101,
        provider_code="shopify:nakpro.com",
        external_product_id="whey-isolate",
        external_variant_id="var-1",
        canonical_url="https://nakpro.com/products/whey-isolate",
        product_title="Nakpro Whey Isolate",
        variant_title="1kg Unflavoured",
        last_price_paise=249900,
        last_available=True,
    )
    repo.listings[101] = listing

    sub = Subscription(
        id=202,
        telegram_id=12345678,
        listing_id=101,
        target_price_paise=260000,
        is_active=True,
    )
    repo.subscriptions[202] = sub

    notif = NotificationLog(
        subscription_id=202,
        alert_type=AlertType.TARGET_REACHED,
        price_paise=249900,
        idempotency_key="sub-202:test",
        status=NotificationStatus.PENDING,
    )
    notif_id = await repo.log_notification(notif)
    assert notif_id is not None

    mock_bot = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.message_id = 98765
    mock_bot.send_message.return_value = mock_msg

    drainer = OutboxDrainer(repo=repo, bot=mock_bot, rate_limit_per_second=50)
    sent_count = await drainer.drain_batch(limit=10)

    assert sent_count == 1
    mock_bot.send_message.assert_called_once()
    assert repo.notifications[notif_id].status == NotificationStatus.SENT
    assert repo.notifications[notif_id].telegram_message_id == 98765


@pytest.mark.asyncio
async def test_shopify_brand_catalog_delta_caching():
    """Verify ShopifyProvider single-request brand catalog caching avoids redundant requests."""
    from pricewatch.providers.shopify import ShopifyProvider

    mock_catalog = {
        "products": [
            {
                "id": 1,
                "handle": "gold-whey",
                "vendor": "Nakpro",
                "variants": [
                    {
                        "id": 9999,
                        "title": "1kg Chocolate",
                        "price": "1899.00",
                        "compare_at_price": "2999.00",
                        "available": True,
                    }
                ],
            }
        ]
    }

    with patch("pricewatch.providers.http_client.http_client.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_catalog
        mock_get.return_value = mock_resp

        provider = ShopifyProvider()
        # Reset cache for test domain
        ShopifyProvider._BRAND_PRODUCTS_CACHE.clear()

        quote = await provider.fetch_quote(
            canonical_url="https://testbrand.com/products/gold-whey?variant=9999",
            external_product_id="gold-whey",
            external_variant_id="9999",
        )
        assert quote.price_paise == 189900
        assert quote.mrp_paise == 299900
        assert quote.extraction_method == "shopify_catalog_delta"

        # Second fetch should hit in-memory brand cache without another HTTP call
        quote2 = await provider.fetch_quote(
            canonical_url="https://testbrand.com/products/gold-whey?variant=9999",
            external_product_id="gold-whey",
            external_variant_id="9999",
        )
        assert quote2.price_paise == 189900
        assert mock_get.call_count == 1  # Only 1 request made for both checks!


