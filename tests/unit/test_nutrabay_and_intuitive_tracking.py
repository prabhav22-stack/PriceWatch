"""Unit tests for NutrabayProvider and intuitive /track multi-mode workflow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import track_handler
from pricewatch.bot.keyboards import build_target_price_keyboard, build_tracking_mode_keyboard
from pricewatch.domain.enums import AlertType
from pricewatch.domain.models import CanonicalListing, PriceQuote, Subscription
from pricewatch.providers.base import ProviderRegistry
from pricewatch.providers.nutrabay import NutrabayProvider
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.alert_service import AlertService
from pricewatch.services.tracker_service import TrackerService


def test_nutrabay_provider_registration_and_can_handle():
    url = "https://nutrabay.com/product/nutrabay-pure-shilajit/?pId=9303750&vId=4609770&pa_weight=20+g+%280.04+lb%29"
    provider = ProviderRegistry.get_provider_for_url(url)
    assert isinstance(provider, NutrabayProvider)
    assert NutrabayProvider.can_handle(url) is True
    assert NutrabayProvider.can_handle("https://nakpro.com/products/whey") is False


def test_tracking_mode_keyboard_structure():
    kb = build_tracking_mode_keyboard(listing_id=10, current_price_paise=49900, is_in_stock=False)
    button_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "trk_mode:10:auto" in button_data
    assert "trk_mode:10:target" in button_data
    assert "trk:cancel" in button_data


@pytest.mark.asyncio
async def test_track_handler_interactive_prompt_no_args():
    update = MagicMock()
    update.effective_user.id = 123456
    update.effective_message.reply_html = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    await track_handler(update, context)

    assert context.user_data.get("awaiting_track_url") is True
    update.effective_message.reply_html.assert_called_once()
    prompt_sent = update.effective_message.reply_html.call_args[0][0]
    assert "Send Product Link to Track" in prompt_sent
    assert "Nutrabay" in prompt_sent


@pytest.mark.asyncio
async def test_trk_mode_auto_tracking_without_target_price():
    repo = MemoryRepository()
    tracker_service = TrackerService(repo, repo, repo)

    # Create listing
    listing = await repo.get_or_create_listing(
        CanonicalListing(
            id=10,
            provider_code="nutrabay",
            provider_tier=1,
            external_product_id="9303750",
            external_variant_id="4609770",
            canonical_url="https://nutrabay.com/product/shilajit",
            product_title="Nutrabay Pure Shilajit",
            variant_title="20g",
            last_price_paise=49900,
            last_available=False,
            is_monitored=True,
        )
    )

    query = MagicMock()
    query.data = f"trk_mode:{listing.id}:auto"
    query.from_user.id = 123456
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    context = MagicMock()
    context.bot_data = {"tracker_service": tracker_service}
    context.user_data = {}

    await callback_query_dispatcher(update, context)

    subs = await repo.get_user_subscriptions(123456)
    assert len(subs) == 1
    sub, saved_listing = subs[0]
    assert sub.listing_id == listing.id
    assert sub.notify_on_restock is True
    assert sub.alert_rearmed is True  # rearmed because currently OOS
    query.edit_message_text.assert_called_once()
    conf_text = query.edit_message_text.call_args[0][0]
    assert "Auto-Tracker Activated!" in conf_text
    assert "Restock Alerts:" in conf_text
    assert "Discount Alerts:" in conf_text


def test_evaluate_alert_separates_restock_and_discount():
    listing = CanonicalListing(
        id=10,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Shilajit",
        last_price_paise=49900,
        last_available=False,  # Previously Out of Stock!
    )

    sub = Subscription(
        id=1,
        telegram_id=123456,
        listing_id=10,
        target_price_paise=49900,
        notify_on_restock=True,
        alert_rearmed=True,
    )

    # 1. Product comes back in stock at same price
    quote_in_stock = PriceQuote(
        external_product_id="9303750",
        external_variant_id="4609770",
        price_paise=49900,
        available=True,
        extraction_method="nutrabay:next_data",
    )

    alert = AlertService.evaluate_alert(
        sub=sub,
        quote=quote_in_stock,
        listing=listing,
    )
    # Must trigger RESTOCK!
    assert alert == AlertType.RESTOCK

    # 2. Product is already in stock (last_available=True) and price drops significantly
    listing_in_stock = listing.model_copy(update={"last_available": True})
    quote_discount = PriceQuote(
        external_product_id="9303750",
        external_variant_id="4609770",
        price_paise=42000,  # ~15% drop below 49900
        available=True,
        extraction_method="nutrabay:next_data",
    )
    summary_30d = {
        "min_price": 49000,
        "max_price": 55000,
        "median_price": 50000,
        "avg_price": 51000,
        "count": 10,
    }

    alert_disc = AlertService.evaluate_alert(
        sub=sub,
        quote=quote_discount,
        listing=listing_in_stock,
        price_summary_30d=summary_30d,
    )
    # Must trigger SIGNIFICANT_DROP!
    assert alert_disc == AlertType.SIGNIFICANT_DROP


def test_nutrabay_quote_with_user_pincode_passes_validation():
    from pricewatch.validation.price_validator import PriceValidator, ValidationStatus
    listing = CanonicalListing(
        id=20,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        pincode="842002",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Shilajit",
        last_price_paise=49900,
        last_available=True,
    )
    quote = PriceQuote(
        external_product_id="9303750",
        external_variant_id="4609770",
        price_paise=49900,
        available=True,
        verified_pincode="",  # Nationwide store does not verify hyperlocal delivery pincode
        extraction_method="nutrabay:next_data",
    )
    decision = PriceValidator.validate(quote, listing)
    assert decision.status == ValidationStatus.VALID, f"Failed with: {decision.reason}"


@pytest.mark.asyncio
async def test_plain_text_guidance_response():
    from pricewatch.bot.handlers.commands import plain_text_handler
    from unittest.mock import AsyncMock, MagicMock

    update = MagicMock()
    update.effective_user.id = 999
    update.effective_message.text = "Hello there"
    update.effective_message.reply_html = AsyncMock()

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"tracker_service": MagicMock()}

    await plain_text_handler(update, context)

    update.effective_message.reply_html.assert_called_once()
    reply_text = update.effective_message.reply_html.call_args[0][0]
    assert "PriceWatch Assistant" in reply_text
    assert "Paste any product link" in reply_text


@pytest.mark.asyncio
async def test_callback_nav_home_and_back_buttons():
    from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
    from pricewatch.bot.keyboards import (
        build_welcome_keyboard,
        build_amul_category_keyboard,
        build_settings_keyboard,
        build_pincode_keyboard,
        build_action_nav_keyboard,
    )
    from pricewatch.domain.models import User
    from unittest.mock import AsyncMock, MagicMock

    # 1. Test keyboards have home / back button
    action_kb = build_action_nav_keyboard("Test Btn", "test:cb")
    assert any("Main Menu" in btn.text for row in action_kb.inline_keyboard for btn in row)

    cat_kb = build_amul_category_keyboard()
    assert any("Main Menu" in btn.text for row in cat_kb.inline_keyboard for btn in row)

    user = User(telegram_id=999, username="test", max_notify_count=1)
    set_kb = build_settings_keyboard(user)
    assert any("Main Menu" in btn.text for row in set_kb.inline_keyboard for btn in row)

    pin_kb = build_pincode_keyboard()
    assert any("Main Menu" in btn.text for row in pin_kb.inline_keyboard for btn in row)

    # 2. Test nav:home callback query
    update = MagicMock()
    query = update.callback_query
    query.data = "nav:home"
    query.from_user.id = 999
    query.from_user.first_name = "Alex"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    repo = MemoryRepository()
    tracker_service = TrackerService(repo, repo, repo)
    context = MagicMock()
    context.bot_data = {"tracker_service": tracker_service}

    await callback_query_dispatcher(update, context)

    query.edit_message_text.assert_called_once()
    welcome_text = query.edit_message_text.call_args[0][0]
    assert "Welcome to PriceWatch 2.0, Alex!" in welcome_text


def test_nutrabay_last_in_stock_formatting():
    from datetime import datetime, timezone
    from pricewatch.bot.formatters import format_nutrabay_stock_report, format_stepwise_product_preview

    stock_time = datetime(2026, 10, 29, 2, 0, 24, tzinfo=timezone.utc)
    listing = CanonicalListing(
        id=50,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20 g (0.04 lb)",
        last_price_paise=49900,
        last_mrp_paise=94900,
        last_available=False,
        inventory_quantity=0,
        last_in_stock_at=stock_time,
        warehouse_stock={"NWH": 0, "ER1": 0, "PBW": 0},
    )

    report = format_nutrabay_stock_report(listing)
    assert "Nutrabay Stock & Availability Report" in report
    assert "Out of Stock" in report
    assert "Last in Stock / Status Change:" in report
    assert "07:30 AM" in report
    assert "North Warehouse (NWH):</b> 0 units" in report

    preview = format_stepwise_product_preview(listing)
    assert "Out of Stock" in preview
    assert "Last in Stock / Status Change:" in preview
    assert "07:30 AM" in preview


@pytest.mark.asyncio
async def test_nutrabay_stock_report_callback():
    from datetime import datetime, timezone
    from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
    from unittest.mock import AsyncMock, MagicMock

    repo = MemoryRepository()
    stock_time = datetime(2026, 10, 29, 2, 0, 24, tzinfo=timezone.utc)
    listing = CanonicalListing(
        id=77,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20 g",
        last_price_paise=49900,
        last_available=False,
        last_in_stock_at=stock_time,
        warehouse_stock={"NWH": 0, "ER1": 0},
    )
    repo.listings[77] = listing
    tracker_service = TrackerService(repo, repo, repo)

    update = MagicMock()
    query = update.callback_query
    query.data = "nb_stock:77"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"tracker_service": tracker_service}

    await callback_query_dispatcher(update, context)

    query.edit_message_text.assert_called_once()
    msg_text = query.edit_message_text.call_args[0][0]
    assert "Nutrabay Stock & Availability Report" in msg_text
    assert "Out of Stock" in msg_text
    assert "Last in Stock / Status Change:" in msg_text


@pytest.mark.asyncio
async def test_nutrabay_fetch_quote_direct_api_fast_path():
    provider = NutrabayProvider()
    mock_payload = {
        "sale_price": "499",
        "mrp": "949",
        "stock_status": True,
        "stock_quantity": 42,
        "variant_swatch_name": "20 g",
        "updated_at": "2026-10-29 02:00:24.035920",
        "wh_meta": {"NWH": 30, "ER1": 12},
    }

    with patch.object(provider, "_fetch_variant_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_payload
        quote = await provider.fetch_quote(
            canonical_url="https://nutrabay.com/product/shilajit",
            external_product_id="9303750",
            external_variant_id="4609770",
        )
        assert quote.price_paise == 49900
        assert quote.mrp_paise == 94900
        assert quote.available is True
        assert quote.inventory_quantity == 42
        assert quote.extraction_method == "nutrabay:rest_api"
        assert quote.warehouse_stock == {"NWH": 30, "ER1": 12}
        assert quote.last_in_stock_at is not None
        mock_api.assert_called_once_with("9303750", "4609770")


@pytest.mark.asyncio
async def test_nutrabay_fetch_quote_fallback_to_next_data():
    provider = NutrabayProvider()
    mock_next_data = {
        "props": {
            "pageProps": {
                "initialState": {
                    "parentProduct": {
                        "getParentDetails": {"data": {"data": {}}},
                        "getVariantDetails": {
                            "data": {
                                "data": {
                                    "variant_product_id": "4609770",
                                    "sale_price": 549,
                                    "regular_price": 999,
                                    "stock_status": False,
                                    "stock_quantity": 0,
                                    "variant_swatch_name": "20 g",
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    with patch.object(provider, "_fetch_variant_api", new_callable=AsyncMock) as mock_api, \
         patch.object(provider, "_fetch_next_data", new_callable=AsyncMock) as mock_next:
        mock_api.return_value = None  # Simulates API failure / fallback
        mock_next.return_value = (mock_next_data, MagicMock())

        quote = await provider.fetch_quote(
            canonical_url="https://nutrabay.com/product/shilajit",
            external_product_id="9303750",
            external_variant_id="4609770",
        )
        assert quote.price_paise == 54900
        assert quote.available is False
        assert quote.extraction_method == "nutrabay:next_data"
        mock_next.assert_called_once_with("https://nutrabay.com/product/shilajit")

