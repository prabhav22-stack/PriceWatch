"""Unit tests for Cross-Store Discovery & Price Comparison engine."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.bot.formatters import format_comparison_report, format_instock_report
from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import compare_command_handler, instock_command_handler, plain_text_handler
from pricewatch.bot.keyboards import (
    build_comparison_keyboard,
    build_instock_keyboard,
    build_listing_card_keyboard,
    build_tracking_mode_keyboard,
)
from pricewatch.domain.models import CanonicalListing, ComparisonResult, StoreDeal, Subscription
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.discovery_matcher import (
    clean_product_tokens,
    compute_match_score,
    extract_brand,
    extract_weight_in_grams,
)
from pricewatch.services.discovery_service import DiscoveryService
from pricewatch.services.tracker_service import TrackerService
from pricewatch.services.vision_extractor import vision_extractor


def test_extract_weight_in_grams():
    assert extract_weight_in_grams("Nutrabay Pure Shilajit 20 g (0.04 lb)") == 20
    assert extract_weight_in_grams("Nakpro Impact Whey 1 kg") == 1000
    assert extract_weight_in_grams("Isolate Protein 2.2 lbs") == 998
    assert extract_weight_in_grams("MuscleBlaze Creatine 250 gm") == 250
    assert extract_weight_in_grams("Multivitamin 60 Tabs") == 60
    assert extract_weight_in_grams("Testosterone Booster 90 tablets") == 90
    assert extract_weight_in_grams("Product Without Weight") is None


def test_extract_brand():
    assert extract_brand("Nutrabay Pure Himalayan Shilajit") == "nutrabay"
    assert extract_brand("Nakpro Perform Whey") == "nakpro"
    assert extract_brand("MuscleBlaze Biozyme Gold") == "muscleblaze"
    assert extract_brand("ATOM Whey Protein by AS-IT-IS") in ("atom", "as-it-is", "asitis")
    assert extract_brand("Generic Random Item") is None


def test_clean_product_tokens():
    cleaned = clean_product_tokens("100% Pure Organic Ayurvedic Shilajit Resin for Men")
    assert "pure" not in cleaned
    assert "organic" not in cleaned
    assert "men" not in cleaned
    assert "shilajit" in cleaned
    assert "resin" in cleaned


def test_compute_match_score_exact_vs_mismatches():
    # 1. Matching product with slight variations in wording
    score1, ok1 = compute_match_score(
        query_title="Nutrabay Pure Shilajit 20g",
        candidate_title="Nutrabay Shilajit Resin 20 grams",
        target_weight_g=20,
        candidate_weight_g=20,
    )
    assert ok1 is True
    assert score1 >= 0.80

    # 2. Conflicting brands must fail
    score2, ok2 = compute_match_score(
        query_title="Nutrabay Pure Shilajit 20g",
        candidate_title="MuscleBlaze Shilajit Gold 20g",
        target_weight_g=20,
        candidate_weight_g=20,
    )
    assert ok2 is False
    assert score2 < 0.50

    # 3. Conflicting sizes must fail
    score3, ok3 = compute_match_score(
        query_title="Nakpro Perform 1kg",
        candidate_title="Nakpro Perform Whey 500g",
        target_weight_g=1000,
        candidate_weight_g=500,
    )
    assert ok3 is False

    # 4. Conflicting category under same brand must fail (e.g. Shilajit vs Zinc Magnesium)
    score4, ok4 = compute_match_score(
        query_title="Nutrabay Shilajit",
        candidate_title="Nutrabay Pro Zinc Magnesium with Vitamin B6 (ZMA) 60 Veg Tablets",
    )
    assert ok4 is False
    assert score4 <= 0.20

    # 5. Conflicting category: Whey vs Buttermilk under Amul
    score5, ok5 = compute_match_score(
        query_title="Amul Whey Protein 1kg",
        candidate_title="Amul High Protein Rose Buttermilk 200ml",
    )
    assert ok5 is False
    assert score5 <= 0.20


def test_construct_search_query():
    q = DiscoveryService.construct_search_query(
        title="Nutrabay Pure Shilajit Resin | Nutrabay",
        variant_title="20 g (0.04 lb)",
    )
    assert "Nutrabay" in q
    assert "Shilajit" in q
    assert "20g" in q


@pytest.mark.asyncio
async def test_discovery_service_compare_listing():
    listing = CanonicalListing(
        id=101,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20g",
        last_price_paise=49900,
        last_available=False,  # OOS on Nutrabay!
    )

    mock_external_deals = [
        StoreDeal(
            store_name="HyugaLife",
            product_title="Nutrabay Shilajit 20g",
            price_paise=44900,
            available=True,
            url="https://hyugalife.com/product/nutrabay-shilajit",
            match_score=0.95,
            spec_weight_g=20,
        ),
        StoreDeal(
            store_name="HealthKart",
            product_title="Nutrabay Shilajit 20g",
            price_paise=47900,
            available=True,
            url="https://healthkart.com/sv/nutrabay-shilajit",
            match_score=0.92,
            spec_weight_g=20,
        ),
    ]

    service = DiscoveryService()
    with patch("pricewatch.services.discovery_service.query_all_stores", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = mock_external_deals

        result = await service.compare_listing(listing)

        assert result.query_title == "Nutrabay Pure Shilajit"
        assert result.best_deal is not None
        assert result.best_deal.store_name == "HyugaLife"
        assert result.best_deal.price_paise == 44900
        assert result.best_deal.savings_paise == 5000  # 499 - 449 = 50 INR (5000 paise)
        assert result.best_deal.is_best_deal is True

        # Ranked: In-stock deals first (HyugaLife @ 449, HealthKart @ 479), then OOS (Nutrabay @ 499)
        assert result.deals[0].store_name == "HyugaLife"
        assert result.deals[1].store_name == "HealthKart"
        assert result.deals[2].store_name == "Nutrabay"
        assert result.deals[2].available is False


def test_format_comparison_report():
    bd = StoreDeal(
        store_name="HyugaLife",
        product_title="Nutrabay Shilajit 20g",
        price_paise=44900,
        mrp_paise=89900,
        available=True,
        url="https://hyugalife.com/product/shilajit",
        savings_paise=5000,
        is_best_deal=True,
    )
    deal_oos = StoreDeal(
        store_name="Nutrabay",
        product_title="Nutrabay Shilajit 20g",
        price_paise=49900,
        available=False,
        url="https://nutrabay.com/product/shilajit",
    )
    res = ComparisonResult(
        query_title="Nutrabay Pure Shilajit",
        target_weight_g=20,
        reference_price_paise=49900,
        reference_store="Nutrabay",
        best_deal=bd,
        deals=[bd, deal_oos],
        stores_checked=2,
    )

    text = format_comparison_report(res)
    assert "Multi-Store Price & Stock Comparison" in text
    assert "HyugaLife" in text
    assert "₹449" in text
    assert "Save ₹50 compared to Nutrabay" in text
    assert "In Stock" in text
    assert "Out of Stock" in text


def test_keyboards_include_compare_button():
    kb_mode = build_tracking_mode_keyboard(listing_id=12, current_price_paise=49900)
    mode_callbacks = [btn.callback_data for row in kb_mode.inline_keyboard for btn in row]
    assert "cmp:12" in mode_callbacks

    kb_card = build_listing_card_keyboard(listing_id=12)
    card_callbacks = [btn.callback_data for row in kb_card.inline_keyboard for btn in row]
    assert "cmp:12" in card_callbacks


@pytest.mark.asyncio
async def test_compare_command_handler_prompt_no_args():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_message.reply_html = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    await compare_command_handler(update, context)

    assert context.user_data.get("awaiting_compare_query") is True
    update.effective_message.reply_html.assert_called_once()
    prompt = update.effective_message.reply_html.call_args[0][0]
    assert "Find Best Price Across Stores" in prompt


@pytest.mark.asyncio
async def test_compare_callback_handler():
    repo = MemoryRepository()
    listing = CanonicalListing(
        id=88,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20g",
        last_price_paise=49900,
        last_available=False,
    )
    repo.listings[88] = listing
    tracker_service = TrackerService(repo, repo, repo)

    mock_deal = StoreDeal(
        store_name="HyugaLife",
        product_title="Nutrabay Shilajit 20g",
        price_paise=44900,
        available=True,
        url="https://hyugalife.com/deal",
        is_best_deal=True,
    )
    mock_result = ComparisonResult(
        query_title="Nutrabay Pure Shilajit",
        target_weight_g=20,
        best_deal=mock_deal,
        deals=[mock_deal],
        stores_checked=1,
    )

    mock_discovery = MagicMock()
    mock_discovery.compare_listing = AsyncMock(return_value=mock_result)

    update = MagicMock()
    query = update.callback_query
    query.data = "cmp:88"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {
        "tracker_service": tracker_service,
        "discovery_service": mock_discovery,
    }

    await callback_query_dispatcher(update, context)

    query.edit_message_text.assert_called_once()
    report = query.edit_message_text.call_args[0][0]
    assert "Multi-Store Price & Stock Comparison" in report
    assert "HyugaLife" in report
    assert "₹449" in report


@pytest.mark.asyncio
async def test_search_flipkart_parser():
    from pricewatch.services.store_searchers import _search_flipkart_sync

    sample_html = """
    <html><body>
    <div data-id="AYD123">
        <a title="Nutrabay Shudh Himalayan Shilajit Resin 20g" href="/nutrabay-shilajit/p/itm123"></a>
        <div class="Nx9bqj">₹499</div>
    </div>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_html

    with patch("curl_cffi.requests.get", return_value=mock_resp):
        deals = _search_flipkart_sync("Nutrabay Shilajit 20g", target_weight_g=20)
        assert len(deals) == 1
        assert deals[0].store_name == "Flipkart"
        assert deals[0].price_paise == 49900
        assert deals[0].available is True
        assert "itm123" in deals[0].url


@pytest.mark.asyncio
async def test_search_amazon_parser():
    from pricewatch.services.store_searchers import _search_amazon_sync

    sample_html = """
    <html><body>
    <div data-component-type="s-search-result" data-asin="B012345678">
        <h2><span>Nakpro Perform Whey Protein 1kg</span></h2>
        <span class="a-price"><span class="a-offscreen">₹2,089</span></span>
    </div>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_html

    with patch("curl_cffi.requests.get", return_value=mock_resp):
        deals = _search_amazon_sync("Nakpro Perform Whey 1kg", target_weight_g=1000)
        assert len(deals) == 1
        assert deals[0].store_name == "Amazon.in"
        assert deals[0].price_paise == 208900
        assert "B012345678" in deals[0].url


@pytest.mark.asyncio
async def test_find_in_stock_alternative_and_notify():
    from pricewatch.bot.formatters import format_cross_store_alert
    from pricewatch.bot.handlers.commands import notify_if_available_elsewhere

    listing = CanonicalListing(
        id=99,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20g",
        last_price_paise=49900,
        last_available=False,
    )
    alt_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Shudh Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/p/123",
    )

    alert_msg = format_cross_store_alert(listing, alt_deal)
    assert "Found In Stock on Flipkart!" in alert_msg
    assert "Out of Stock on Nutrabay" in alert_msg
    assert "₹499" in alert_msg

    # Test notify_if_available_elsewhere
    mock_discovery = MagicMock()
    mock_discovery.find_in_stock_alternative = AsyncMock(return_value=alt_deal)

    context = MagicMock()
    context.bot_data = {"discovery_service": mock_discovery}
    context.user_data = {}
    context.bot.send_message = AsyncMock()

    await notify_if_available_elsewhere(
        chat_id=1234,
        user_id=5678,
        listing=listing,
        context=context,
    )

    context.bot.send_message.assert_called_once()
    sent_text = context.bot.send_message.call_args[1]["text"]
    assert "Found In Stock on Flipkart!" in sent_text
    assert context.user_data.get("alt_deal_99") == alt_deal


@pytest.mark.asyncio
async def test_switch_tracking_callback():
    repo = MemoryRepository()
    old_listing = CanonicalListing(
        id=55,
        provider_code="nutrabay",
        external_product_id="9303750",
        external_variant_id="4609770",
        canonical_url="https://nutrabay.com/product/shilajit",
        product_title="Nutrabay Pure Shilajit",
        variant_title="20g",
        last_price_paise=49900,
        last_available=False,
    )
    new_listing = CanonicalListing(
        id=56,
        provider_code="flipkart",
        external_product_id="itm123",
        external_variant_id="default",
        canonical_url="https://flipkart.com/shilajit/p/123",
        product_title="Nutrabay Shudh Shilajit Resin 20g",
        variant_title="20g",
        last_price_paise=49900,
        last_available=True,
    )
    repo.listings[55] = old_listing
    repo.listings[56] = new_listing

    # User initially subscribed to old listing
    sub = Subscription(
        id=1,
        telegram_id=777,
        listing_id=55,
        target_price_paise=49900,
        is_active=True,
    )
    await repo.create_or_update_subscription(sub)

    tracker_service = TrackerService(repo, repo, repo)
    tracker_service.resolve_and_preview_url = AsyncMock(return_value=new_listing)

    alt_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Shudh Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/p/123",
    )

    update = MagicMock()
    query = update.callback_query
    query.data = "sw_trk:55"
    query.from_user.id = 777
    query.from_user.username = "tester"
    query.from_user.first_name = "Alex"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"tracker_service": tracker_service}
    context.user_data = {"alt_deal_55": alt_deal}

    await callback_query_dispatcher(update, context)

    # Old subscription must be inactive
    old_subs = [s for s in repo.subscriptions.values() if s.telegram_id == 777 and s.listing_id == 55]
    assert len(old_subs) == 1
    assert old_subs[0].is_active is False

    # New subscription on listing 56 must be active
    new_subs = [s for s in repo.subscriptions.values() if s.telegram_id == 777 and s.listing_id == 56]
    assert len(new_subs) == 1
    assert new_subs[0].is_active is True

    query.edit_message_text.assert_called_once()
    conf_msg = query.edit_message_text.call_args[0][0]
    assert "Successfully Switched Tracking to Flipkart!" in conf_msg


def test_format_instock_report_and_keyboard():
    deal_in_stock = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Pure Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/123",
        is_best_deal=True,
    )
    deal_oos = StoreDeal(
        store_name="Nutrabay",
        product_title="Nutrabay Pure Shilajit 20g",
        price_paise=54900,
        available=False,
        url="https://nutrabay.com/shilajit/123",
    )
    res = ComparisonResult(
        query_title="Nutrabay Shilajit",
        target_weight_g=20,
        best_deal=deal_in_stock,
        deals=[deal_in_stock, deal_oos],
        stores_checked=2,
    )

    report = format_instock_report(res)
    assert "Instant Stock Finder" in report
    assert "Nutrabay Shilajit" in report
    assert "IN STOCK at 1 store right now!" in report
    assert "Flipkart" in report
    assert "₹499" in report
    assert "Nutrabay:" not in report  # Out of stock store excluded from in-stock list

    kb = build_instock_keyboard(res)
    buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("Flipkart" in b for b in buttons)


def test_format_instock_report_all_out_of_stock():
    deal_oos = StoreDeal(
        store_name="Amazon.in",
        product_title="Rare Supplement 500g",
        price_paise=129900,
        available=False,
        url="https://amazon.in/dp/B001",
    )
    res = ComparisonResult(
        query_title="Rare Supplement",
        target_weight_g=500,
        best_deal=None,
        deals=[deal_oos],
        stores_checked=3,
    )

    report = format_instock_report(res)
    assert "OUT OF STOCK across all checked stores" in report
    assert "Restock Alert" in report


@pytest.mark.asyncio
async def test_instock_command_handler_no_args():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_message.reply_html = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    await instock_command_handler(update, context)

    assert context.user_data.get("awaiting_instock_query") is True
    update.effective_message.reply_html.assert_called_once()
    msg = update.effective_message.reply_html.call_args[0][0]
    assert "Instant Stock Finder" in msg


@pytest.mark.asyncio
async def test_instock_command_handler_with_query():
    update = MagicMock()
    update.effective_user.id = 12345
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    update.effective_message.reply_html = AsyncMock(return_value=status_msg)

    context = MagicMock()
    context.args = ["Nutrabay", "Shilajit"]
    mock_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Pure Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/123",
        is_best_deal=True,
    )
    mock_result = ComparisonResult(
        query_title="Nutrabay Shilajit",
        target_weight_g=20,
        best_deal=mock_deal,
        deals=[mock_deal],
        stores_checked=1,
    )
    mock_disc_svc = MagicMock()
    mock_disc_svc.compare_query = AsyncMock(return_value=mock_result)
    context.bot_data = {"discovery_service": mock_disc_svc}

    await instock_command_handler(update, context)

    status_msg.edit_text.assert_called_once()
    edited_text = status_msg.edit_text.call_args[0][0]
    assert "Instant Stock Finder" in edited_text
    assert "Flipkart" in edited_text


@pytest.mark.asyncio
async def test_offline_ocr_extractor_on_screenshot():
    import os
    path = "C:/Users/prabh/.gemini/antigravity/brain/444aad51-7af3-453c-9cc1-2674549d4b00/.user_uploaded/media_1793503213696_b33884aa.jpg"
    if not os.path.exists(path):
        pytest.skip("User screenshot not present on disk")

    with open(path, "rb") as f:
        img_bytes = f.read()

    # Ensure settings.GEMINI_API_KEY is unset so it exercises local OCR
    with patch("pricewatch.services.vision_extractor.settings.GEMINI_API_KEY", None):
        product = await vision_extractor.extract_from_image_bytes(img_bytes)
        assert product is not None
        assert "Nutrabay" in product.title or (product.brand and "nutrabay" in product.brand.lower())


@pytest.mark.asyncio
async def test_check_command_handler_shows_alternative_in_stock():
    from pricewatch.bot.handlers.commands import check_command_handler
    from pricewatch.domain.models import PriceQuote
    from pricewatch.services.check_orchestrator import CheckResult

    repo = MemoryRepository()
    listing = CanonicalListing(
        id=99,
        provider_code="nutrabay",
        external_product_id="nb99",
        canonical_url="https://nutrabay.com/item",
        product_title="Nutrabay Pure Shilajit",
        last_price_paise=49900,
        last_available=False,
    )
    repo.listings[99] = listing
    sub = Subscription(id=1, telegram_id=888, listing_id=99, target_price_paise=45000)
    await repo.create_or_update_subscription(sub)

    tracker_service = TrackerService(repo, repo, repo)
    alt_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/99",
    )
    mock_disc_svc = MagicMock()
    mock_disc_svc.find_in_stock_alternative = AsyncMock(return_value=alt_deal)

    update = MagicMock()
    update.effective_user.id = 888
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    update.effective_message.reply_html = AsyncMock(return_value=status_msg)

    context = MagicMock()
    context.bot_data = {
        "tracker_service": tracker_service,
        "discovery_service": mock_disc_svc,
    }

    mock_check_res = CheckResult(
        listing_id=99,
        quote=PriceQuote(
            external_product_id="nb99",
            external_variant_id="nb99",
            extraction_method="test",
            price_paise=49900,
            available=False,
        ),
        decision=None,
        is_verified=True,
        success=True,
    )

    with patch("pricewatch.bot.handlers.commands.CheckOrchestrator") as mock_orch_cls:
        mock_orch = MagicMock()
        mock_orch.check_listing = AsyncMock(return_value=mock_check_res)
        mock_orch_cls.return_value = mock_orch

        await check_command_handler(update, context)

    status_msg.edit_text.assert_called_once()
    output_text = status_msg.edit_text.call_args[0][0]
    assert "Live Stock & Price Check" in output_text
    assert "Out of Stock" in output_text
    assert "<b>IN STOCK on Flipkart:</b> <code>₹499</code>" in output_text
    assert "https://flipkart.com/shilajit/99" in output_text


@pytest.mark.asyncio
async def test_instock_command_handler_with_listing_id():
    repo = MemoryRepository()
    listing = CanonicalListing(
        id=77,
        provider_code="nutrabay",
        external_product_id="nb77",
        canonical_url="https://nutrabay.com/item",
        product_title="Nutrabay Pure Shilajit",
        last_price_paise=49900,
        last_available=False,
    )
    repo.listings[77] = listing
    tracker_service = TrackerService(repo, repo, repo)

    mock_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Pure Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/77",
        is_best_deal=True,
    )
    mock_result = ComparisonResult(
        query_title="Nutrabay Pure Shilajit",
        target_weight_g=20,
        best_deal=mock_deal,
        deals=[mock_deal],
        stores_checked=1,
    )
    mock_disc_svc = MagicMock()
    mock_disc_svc.compare_listing = AsyncMock(return_value=mock_result)

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_message.text = "/instock_77"
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    update.effective_message.reply_html = AsyncMock(return_value=status_msg)

    context = MagicMock()
    context.args = []
    context.bot_data = {
        "tracker_service": tracker_service,
        "discovery_service": mock_disc_svc,
    }

    await instock_command_handler(update, context)

    status_msg.edit_text.assert_called_once()
    edited_text = status_msg.edit_text.call_args[0][0]
    assert "Instant Stock Finder" in edited_text
    assert "Flipkart" in edited_text


@pytest.mark.asyncio
async def test_stk_callback_handler():
    repo = MemoryRepository()
    listing = CanonicalListing(
        id=66,
        provider_code="nutrabay",
        external_product_id="nb66",
        canonical_url="https://nutrabay.com/item",
        product_title="Nutrabay Pure Shilajit",
        last_price_paise=49900,
        last_available=False,
    )
    repo.listings[66] = listing
    tracker_service = TrackerService(repo, repo, repo)

    mock_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nutrabay Pure Shilajit Resin 20g",
        price_paise=49900,
        available=True,
        url="https://flipkart.com/shilajit/66",
        is_best_deal=True,
    )
    mock_result = ComparisonResult(
        query_title="Nutrabay Pure Shilajit",
        target_weight_g=20,
        best_deal=mock_deal,
        deals=[mock_deal],
        stores_checked=1,
    )
    mock_disc_svc = MagicMock()
    mock_disc_svc.compare_listing = AsyncMock(return_value=mock_result)

    update = MagicMock()
    query = update.callback_query
    query.data = "stk:66"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {
        "tracker_service": tracker_service,
        "discovery_service": mock_disc_svc,
    }

    await callback_query_dispatcher(update, context)

    query.edit_message_text.assert_called_once()
    text = query.edit_message_text.call_args[0][0]
    assert "Instant Stock Finder" in text
    assert "Flipkart" in text



