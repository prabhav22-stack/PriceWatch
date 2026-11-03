"""Unit tests for the 5 newly integrated stacks:
1. Groq Whisper Voice Assistant (audio transcription)
2. DuckDB Deal & Glitch Hunter (/deals command)
3. Semantic Fitness & Dietary Goal Search
4. Interactive Telegram Mini App (TMA) Catalog & Filter Drawer
5. Automated On-Page Coupon Extractor
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from pricewatch.services.llm_router import llm_router
from pricewatch.services.deal_hunter import deal_hunter, DealItem
from pricewatch.services.semantic_search import semantic_search
from pricewatch.services.coupon_service import coupon_service
from pricewatch.domain.models import CanonicalListing, PriceObservation


# --- 1. Groq Whisper Voice Assistant Tests ---
@pytest.mark.asyncio
async def test_groq_whisper_transcription_success():
    """Verify Groq Whisper endpoint returns transcribed text from audio bytes."""
    fake_audio = b"\x00\x01\x02\x03\x04"
    with patch.object(llm_router, "groq_api_key", "gsk_testkey1234567890"), \
         patch.object(
             llm_router,
             "_transcribe_via_groq",
             new_callable=AsyncMock,
             return_value="top 5 isolate whey under 2000",
         ):
        transcription = await llm_router.transcribe_audio(fake_audio)
        assert transcription == "top 5 isolate whey under 2000"


@pytest.mark.asyncio
async def test_groq_whisper_empty_audio_returns_none():
    """Empty audio payload gracefully returns None without error."""
    assert await llm_router.transcribe_audio(b"") is None


# --- 2. DuckDB Deal & Glitch Hunter Tests ---
def test_duckdb_deal_hunter_olap():
    """Verify DuckDB analytical queries compute all-time lows and glitches."""
    listings = [
        CanonicalListing(
            id=1,
            provider_code="amazon",
            external_product_id="B082F3M6GZ",
            canonical_url="https://amazon.in/dp/B082F3M6GZ",
            product_title="Nakpro Platinum 100% Whey Isolate 1kg",
            last_price_paise=219900,
            last_mrp_paise=369900,
            last_available=True,
        ),
        CanonicalListing(
            id=2,
            provider_code="flipkart",
            external_product_id="MBBIO1KG",
            canonical_url="https://flipkart.com",
            product_title="MuscleBlaze Biozyme Performance Whey 1kg",
            last_price_paise=209900,
            last_mrp_paise=279900,
            last_available=True,
        ),
    ]

    observations = [
        PriceObservation(listing_id=1, price_paise=249900, extraction_method="http"),
        PriceObservation(listing_id=1, price_paise=229900, extraction_method="http"),
        PriceObservation(listing_id=1, price_paise=219900, extraction_method="http"),
        PriceObservation(listing_id=2, price_paise=249900, extraction_method="http"),
        PriceObservation(listing_id=2, price_paise=239900, extraction_method="http"),
    ]

    deals = deal_hunter.analyze_deals(listings=listings, observations=observations, limit=5)
    assert len(deals) > 0
    # First product is at all-time low (2199 <= min observation 2199)
    assert any(d.is_all_time_low for d in deals)
    # Check formatting
    report = deal_hunter.format_deals_report(deals)
    assert "TOP DEALS" in report
    assert "DuckDB" in report


def test_duckdb_fallback_deals():
    """Verify fallback seeds return when listings/observations are empty."""
    deals = deal_hunter.analyze_deals(listings=[], observations=[], limit=3)
    assert len(deals) == 3
    assert deals[0].current_price > 0


# --- 3. Semantic Fitness & Dietary Goal Search Tests ---
def test_semantic_search_detects_lactose_sensitivity():
    """Queries mentioning bloating or lactose trigger isolate/enzymes advice."""
    query = "I get severe bloating and gas from whey, what should I buy for cutting?"
    intents = semantic_search.detect_intents(query)
    categories = [i.category for i in intents]
    assert "whey_isolate" in categories

    advice = semantic_search.get_intent_advice(query)
    assert advice is not None
    assert "digestive enzymes" in advice or "Isolate" in advice


def test_semantic_search_product_fit_scoring():
    """Isolate product receives higher compatibility score for lactose sensitive query."""
    query = "lactose intolerant sensitive stomach"
    isolate_score = semantic_search.score_product_fit(query, "Nakpro 100% Whey Protein Isolate DigeZyme")
    concentrate_score = semantic_search.score_product_fit(query, "Standard Whey Protein Concentrate Raw")
    assert isolate_score > concentrate_score


# --- 4. Interactive Telegram Mini App (TMA) Catalog Tests ---
@pytest.mark.asyncio
async def test_tma_catalog_api_and_page():
    """Verify TMA FastAPI server returns catalog items and HTML dashboard."""
    from pricewatch.webapp.server import app
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # API JSON check
        api_res = await ac.get("/api/v1/catalog")
        assert api_res.status_code == 200
        data = api_res.json()
        assert "items" in data
        assert len(data["items"]) > 0

        # HTML page check
        page_res = await ac.get("/webapp/catalog")
        assert page_res.status_code == 200
        assert "PriceWatch Supplement Catalog" in page_res.text
        assert "Telegram.WebApp" in page_res.text


# --- 5. Automated On-Page Coupon Extractor Tests ---
def test_coupon_extractor_fixed_rupees():
    """Detects 'Apply ₹200 coupon' on Amazon and calculates effective price."""
    snippet = "Nakpro Platinum Isolate 1kg. Apply ₹200 coupon at checkout."
    current_price = 2199.0
    info = coupon_service.extract_coupon(snippet, current_price)
    assert info.has_coupon is True
    assert info.discount_amount == 200.0
    assert info.effective_price == 1999.0
    md = coupon_service.format_coupon_markdown(info)
    assert "Save ₹200" in md
    assert "₹1,999" in md


def test_coupon_extractor_percentage_discount():
    """Detects 'Save 10% with coupon' and computes effective price."""
    snippet = "Save 10% with coupon checkbox. Nakpro Gold Whey."
    current_price = 1700.0
    info = coupon_service.extract_coupon(snippet, current_price)
    assert info.has_coupon is True
    assert info.discount_amount == 170.0
    assert info.effective_price == 1530.0


def test_coupon_extractor_no_coupon():
    """Returns has_coupon=False when no coupon patterns are found."""
    snippet = "Regular MuscleBlaze Biozyme 1kg bottle without discount code."
    info = coupon_service.extract_coupon(snippet, 2400.0)
    assert info.has_coupon is False
    assert info.effective_price == 2400.0
