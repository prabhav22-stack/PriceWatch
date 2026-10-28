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
    # Case 1: Out of stock product
    kb_oos = build_tracking_mode_keyboard(listing_id=10, current_price_paise=49900, is_in_stock=False)
    button_data = [btn.callback_data for row in kb_oos.inline_keyboard for btn in row]
    assert "trk_mode:10:stock" in button_data
    assert "trk_mode:10:discount" in button_data
    assert "trk_mode:10:both" in button_data
    assert "trk_mode:10:target" in button_data

    # Case 2: In-stock product
    kb_in = build_tracking_mode_keyboard(listing_id=10, current_price_paise=49900, is_in_stock=True)
    button_data_in = [btn.callback_data for row in kb_in.inline_keyboard for btn in row]
    assert "trk_mode:10:stock" in button_data_in
    assert "trk_mode:10:discount" in button_data_in


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
async def test_trk_mode_callbacks_without_target_price():
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

    # 1. Test "stock" mode
    query = MagicMock()
    query.data = f"trk_mode:{listing.id}:stock"
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
    assert "Back-in-Stock Tracker Active!" in conf_text

    # 2. Test "discount" mode
    query.data = f"trk_mode:{listing.id}:discount"
    query.edit_message_text.reset_mock()
    await callback_query_dispatcher(update, context)

    subs = await repo.get_user_subscriptions(123456)
    sub, _ = subs[0]
    assert sub.notify_on_restock is False
    assert sub.alert_rearmed is True
    conf_text = query.edit_message_text.call_args[0][0]
    assert "Significant Discount Tracker Active!" in conf_text


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

    sub_stock = Subscription(
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
        sub=sub_stock,
        quote=quote_in_stock,
        listing=listing,
    )
    # Must trigger RESTOCK, not SIGNIFICANT_DROP!
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

    sub_discount = Subscription(
        id=2,
        telegram_id=123456,
        listing_id=10,
        target_price_paise=35000,  # Unrealistically low target, but significant drop occurs
        notify_on_restock=True,
        alert_rearmed=True,
    )

    alert_disc = AlertService.evaluate_alert(
        sub=sub_discount,
        quote=quote_discount,
        listing=listing_in_stock,
        price_summary_30d=summary_30d,
    )
    # Must trigger SIGNIFICANT_DROP, not RESTOCK!
    assert alert_disc == AlertType.SIGNIFICANT_DROP
