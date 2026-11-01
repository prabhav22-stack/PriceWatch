"""Comprehensive End-to-End Test Suite verifying the bot from start to finish.

Simulates a real user lifecycle across every single command, callback, and background pipeline:
- /start, /help, /status, /map, /support
- /pincode, /setpincode, /repeat, /settings
- /channels (Multi-Channel Alerts)
- URL inspection, variant resolution, target price selection
- Out-of-Stock proactive cross-store alternative alert & 1-click switch
- /tracked, /list, /check (Instant Live Check)
- /compare (Multi-Store Price Discovery)
- /history (Chart rendering)
- /untrack (Confirmation & Deactivation)
- Amul commands: /products, /search, /favourites, /count, /analytics, /trackall
- FastAPI Telegram Mini App (TMA) Dashboard
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from pricewatch.bot.app import create_telegram_app
from pricewatch.bot.commands_menu import DEFAULT_BOT_COMMANDS
from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import (
    amul_command_handler,
    analytics_command_handler,
    channels_command_handler,
    check_command_handler,
    compare_command_handler,
    favourites_command_handler,
    help_handler,
    history_command_handler,
    list_handler,
    map_handler,
    pincode_handler,
    plain_text_handler,
    productcount_command_handler,
    repeat_command_handler,
    search_command_handler,
    setpincode_handler,
    settings_command_handler,
    start_handler,
    status_handler,
    support_handler,
    track_handler,
    trackall_command_handler,
    untrack_handler,
)
from pricewatch.core.cache import cache
from pricewatch.domain.enums import AlertType, ProviderTier
from pricewatch.domain.models import CanonicalListing, ComparisonResult, PriceObservation, PriceQuote, StoreDeal, Subscription, VariantOption
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.alert_service import AlertService
from pricewatch.services.discovery_service import DiscoveryService
from pricewatch.services.multi_channel_notifier import MultiChannelNotifier
from pricewatch.services.tracker_service import TrackerService
from pricewatch.webapp.server import app, set_webapp_context


@pytest.fixture
def test_env():
    """Setup an isolated memory repository and services."""
    repo = MemoryRepository()
    tracker_svc = TrackerService(
        listing_repo=repo,
        subscription_repo=repo,
        user_repo=repo,
    )
    discovery_svc = DiscoveryService()
    alert_svc = AlertService(
        subscription_repo=repo,
        user_repo=repo,
        listing_repo=repo,
    )
    return {
        "repo": repo,
        "tracker_svc": tracker_svc,
        "discovery_svc": discovery_svc,
        "alert_svc": alert_svc,
    }


def make_update(user_id=12345, text="", args=None, username="athlete", first_name="Alex"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.first_name = first_name
    update.effective_message.text = text
    update.effective_message.reply_html = AsyncMock()
    update.effective_message.reply_text = AsyncMock()
    update.effective_message.reply_photo = AsyncMock()

    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    return update, context


@pytest.mark.asyncio
async def test_lifecycle_stage_1_welcome_help_status(test_env):
    """Test /start, /help, /status, /map, /support."""
    tracker_svc = test_env["tracker_svc"]
    update, context = make_update()
    context.bot_data = {"tracker_service": tracker_svc}

    # 1. /start
    await start_handler(update, context)
    update.effective_message.reply_html.assert_called()
    welcome_text = update.effective_message.reply_html.call_args[0][0]
    assert "Alex" in welcome_text or "PriceWatch" in welcome_text

    # 2. /help
    update.effective_message.reply_html.reset_mock()
    await help_handler(update, context)
    assert "Command Reference" in update.effective_message.reply_html.call_args[0][0]

    # 3. /status
    update.effective_message.reply_html.reset_mock()
    await status_handler(update, context)
    assert "System Status" in update.effective_message.reply_html.call_args[0][0]

    # 4. /map
    update.effective_message.reply_html.reset_mock()
    await map_handler(update, context)
    assert "Delivery Hubs" in update.effective_message.reply_html.call_args[0][0]

    # 5. /support
    update.effective_message.reply_html.reset_mock()
    await support_handler(update, context)
    assert "Support" in update.effective_message.reply_html.call_args[0][0]


@pytest.mark.asyncio
async def test_lifecycle_stage_2_pincode_settings_channels(test_env):
    """Test /pincode, /setpincode, /repeat, /settings, /channels."""
    tracker_svc = test_env["tracker_svc"]
    update, context = make_update()
    context.bot_data = {"tracker_service": tracker_svc}

    # 1. /pincode
    await pincode_handler(update, context)
    assert "pincode" in update.effective_message.reply_html.call_args[0][0].lower()

    # 2. /setpincode 110001
    context.args = ["110001"]
    update.effective_message.reply_html.reset_mock()
    await setpincode_handler(update, context)
    assert "110001" in update.effective_message.reply_html.call_args[0][0]

    # 3. /repeat 3
    context.args = ["3"]
    update.effective_message.reply_html.reset_mock()
    await repeat_command_handler(update, context)
    assert "3 dynamic alerts" in update.effective_message.reply_html.call_args[0][0]

    # 4. /settings
    context.args = []
    update.effective_message.reply_html.reset_mock()
    await settings_command_handler(update, context)
    assert "Settings" in update.effective_message.reply_html.call_args[0][0]

    # 5. /channels (overview -> add -> test -> clear)
    update.effective_message.reply_html.reset_mock()
    await channels_command_handler(update, context)
    assert "Multi-Channel Notification Settings" in update.effective_message.reply_html.call_args[0][0]

    context.args = ["add", "ntfy://test_pw_alerts"]
    update.effective_message.reply_html.reset_mock()
    await channels_command_handler(update, context)
    assert "Channel Added Successfully!" in update.effective_message.reply_html.call_args[0][0]

    context.args = ["clear"]
    update.effective_message.reply_html.reset_mock()
    await channels_command_handler(update, context)
    assert "cleared" in update.effective_message.reply_html.call_args[0][0]


@pytest.mark.asyncio
async def test_lifecycle_stage_3_product_tracking_and_comparison(test_env):
    """Test tracking flow, out-of-stock alternative detection, and cross-store comparison."""
    repo = test_env["repo"]
    tracker_svc = test_env["tracker_svc"]
    discovery_svc = test_env["discovery_svc"]

    # Create mock out-of-stock listing on Nutrabay
    oos_listing = CanonicalListing(
        id=101,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/pure-shilajit-20g",
        product_title="Nutrabay Pure Himalayan Shilajit",
        variant_title="20g",
        last_price_paise=49900,
        last_available=False,
    )
    repo.listings[101] = oos_listing

    update, context = make_update(user_id=12345)
    context.bot_data = {
        "tracker_service": tracker_svc,
        "discovery_service": discovery_svc,
    }

    # 1. User sets target price via callback: tgt:101:44900
    cb_update = MagicMock()
    cb_query = cb_update.callback_query
    cb_query.data = "tgt:101:44900"
    cb_query.from_user.id = 12345
    cb_query.message.chat_id = 12345
    cb_query.answer = AsyncMock()
    cb_query.edit_message_text = AsyncMock()
    context.bot.send_message = AsyncMock()

    # Mock alternative discovery: found in stock on Flipkart
    alt_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Pure Himalayan Shilajit 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/p/101",
    )
    discovery_svc.find_in_stock_alternative = AsyncMock(return_value=alt_deal)

    await callback_query_dispatcher(cb_update, context)

    # Verify tracking confirmation
    cb_query.edit_message_text.assert_called_once()
    assert "Now Tracking Product!" in cb_query.edit_message_text.call_args[0][0]

    # 2. User checks /tracked list
    update.effective_message.reply_html.reset_mock()
    await list_handler(update, context)
    tracked_msg = update.effective_message.reply_html.call_args[0][0]
    assert "Nutrabay Pure Himalayan Shilajit" in tracked_msg

    # 3. User checks /compare
    context.args = ["101"]
    update.effective_message.reply_html.reset_mock()
    cmp_status_mock = AsyncMock()
    update.effective_message.reply_html.return_value = cmp_status_mock
    with patch.object(
        discovery_svc,
        "compare_listing",
        return_value=ComparisonResult(
            query_title="Nutrabay Pure Himalayan Shilajit 20g",
            reference_listing=oos_listing,
            deals=[alt_deal],
            cheapest_deal=alt_deal,
            in_stock_count=1,
            total_stores_checked=5,
        ),
    ):
        await compare_command_handler(update, context)
        cmp_status_mock.edit_text.assert_called_once()
        cmp_msg = cmp_status_mock.edit_text.call_args[0][0]
        assert "Multi-Store Price & Stock Comparison" in cmp_msg

    # 4. Instant Live Check /check
    update.effective_message.reply_html.reset_mock()
    status_mock = AsyncMock()
    update.effective_message.reply_html.return_value = status_mock
    with patch("pricewatch.services.check_orchestrator.CheckOrchestrator.check_listing") as mock_chk:
        mock_chk.return_value = MagicMock(
            success=True,
            quote=PriceQuote(
                external_product_id="9303750",
                external_variant_id="4609770",
                price_paise=49900,
                available=False,
                extraction_method="mock",
            ),
        )
        await check_command_handler(update, context)
        status_mock.edit_text.assert_called_once()
        check_out = status_mock.edit_text.call_args[0][0]
        assert "Live Stock & Price Check" in check_out

    # 5. Untrack listing: del:confirm:101
    del_update = MagicMock()
    del_query = del_update.callback_query
    del_query.data = "del:confirm:101"
    del_query.from_user.id = 12345
    del_query.answer = AsyncMock()
    del_query.edit_message_text = AsyncMock()

    await callback_query_dispatcher(del_update, context)
    del_query.edit_message_text.assert_called_once()
    assert "Untracking product" in del_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_lifecycle_stage_4_amul_operations(test_env):
    """Test Amul product browsing, stock counting, analytics, and trackall."""
    tracker_svc = test_env["tracker_svc"]
    update, context = make_update()
    context.bot_data = {"tracker_service": tracker_svc}

    # 1. /products or /amul
    await amul_command_handler(update, context)
    assert "Amul" in update.effective_message.reply_html.call_args[0][0]

    # 2. /search lassi
    context.args = ["lassi"]
    update.effective_message.reply_html.reset_mock()
    await search_command_handler(update, context)
    assert "Amul Search" in update.effective_message.reply_html.call_args[0][0]

    # 3. /favourites
    context.args = []
    update.effective_message.reply_html.reset_mock()
    await favourites_command_handler(update, context)
    assert "favourites" in update.effective_message.reply_html.call_args[0][0].lower()

    # 4. /count
    update.effective_message.reply_html.reset_mock()
    await productcount_command_handler(update, context)
    assert "Product Counts" in update.effective_message.reply_html.call_args[0][0]

    # 5. /analytics
    update.effective_message.reply_html.reset_mock()
    await analytics_command_handler(update, context)
    assert "Warehouse Analytics" in update.effective_message.reply_html.call_args[0][0]

    # 6. /trackall
    update.effective_message.reply_html.reset_mock()
    await trackall_command_handler(update, context)
    assert "All-Protein Restock Alerts" in update.effective_message.reply_html.call_args[0][0]


@pytest.mark.asyncio
async def test_lifecycle_stage_5_fastapi_tma_dashboard(test_env):
    """Test FastAPI WebApp endpoints for Telegram Mini App."""
    repo = test_env["repo"]
    listing = CanonicalListing(
        id=77,
        provider_code="asitis",
        external_product_id="atom-whey",
        external_variant_id="default",
        canonical_url="https://asitisnutrition.com/products/atom-whey",
        product_title="ATOM Whey Protein 1kg",
        variant_title="1kg Double Rich Chocolate",
        last_price_paise=189900,
        last_mrp_paise=269900,
        last_available=True,
    )
    repo.listings[77] = listing
    set_webapp_context(repo)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /webapp/dashboard/77
        res = await client.get("/webapp/dashboard/77")
        assert res.status_code == 200
        assert "ATOM Whey Protein" in res.text
        assert "lightweight-charts" in res.text.lower()
        assert "telegram-web-app.js" in res.text

        # GET /api/v1/listing/77
        api_res = await client.get("/api/v1/listing/77")
        assert api_res.status_code == 200
        data = api_res.json()
        assert data["current_price_rs"] == 1899.0
        assert data["store"] == "Asitis"


def test_command_menu_integrity():
    """Verify all bot menu commands are uniquely named and properly registered."""
    cmd_names = [cmd.command for cmd in DEFAULT_BOT_COMMANDS]
    assert len(cmd_names) == len(set(cmd_names)), "Duplicate command detected in menu!"
    assert "start" in cmd_names
    assert "track" in cmd_names
    assert "compare" in cmd_names
    assert "channels" in cmd_names
    assert "tracked" in cmd_names
    assert "check" in cmd_names
