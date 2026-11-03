"""Unit tests for the 4 newly integrated features:
1. Trustified & Labdoor Purity Verification Service
2. "Buy Now vs Wait" Predictive Buying Advice & Price Forecaster
3. Visual Deal Snapshot Infocard Generator
4. Google Sheets & CSV Portfolio Export Service
"""

import pytest
from pricewatch.domain.models import CanonicalListing, StoreDeal, Subscription
from pricewatch.services.purity_service import purity_service
from pricewatch.services.price_predictor import price_forecaster
from pricewatch.services.deal_card_generator import deal_card_generator
from pricewatch.services.export_service import export_service


def test_purity_service_lookup():
    # 1. Nakpro Perform Whey
    cert = purity_service.lookup("Nakpro Perform Whey Protein 1kg Unflavoured")
    assert cert is not None
    assert cert.brand == "Nakpro"
    assert cert.status == "PASSED"
    assert cert.tested_protein_g == 24.2
    assert cert.claimed_protein_g == 24.0
    assert cert.amino_spiking_detected is False

    badge = purity_service.format_badge_markdown(cert)
    assert "Trustified Lab Test: PASSED" in badge
    assert "24.2g" in badge
    assert "Below Safe Limits" in badge

    # 2. Amul Whey Protein
    amul_cert = purity_service.lookup("Amul Whey Protein 32g Sachets")
    assert amul_cert is not None
    assert amul_cert.brand == "Amul"
    assert amul_cert.status == "PASSED"

    # 3. Unknown generic title
    unknown = purity_service.lookup("Generic Brand Mystery Powder 500g")
    assert unknown is None


def test_price_forecaster_evaluation():
    # Scenario A: Heavy discount -> BUY NOW
    advice_buy = price_forecaster.evaluate(
        current_price_paise=150000,  # ₹1,500
        history_paise=[220000, 215000, 230000, 220000, 150000],  # median ~ ₹2,200
        mrp_paise=300000,
    )
    assert advice_buy.verdict == "BUY NOW"
    assert advice_buy.confidence_pct >= 80
    assert advice_buy.median_price_inr >= 2100.0

    md_buy = price_forecaster.format_advice_markdown(advice_buy)
    assert "BUY NOW" in md_buy
    assert "30-day Median:" in md_buy

    # Scenario B: Elevated price -> WAIT
    advice_wait = price_forecaster.evaluate(
        current_price_paise=260000,  # ₹2,600
        history_paise=[200000, 210000, 205000, 215000, 260000],  # median ~ ₹2,100
        mrp_paise=300000,
    )
    assert advice_wait.verdict == "WAIT"
    assert advice_wait.confidence_pct >= 75


def test_deal_card_generator():
    best_deal = StoreDeal(
        store_name="Flipkart",
        product_title="Nakpro Perform Whey Protein 1kg Unflavoured",
        price_paise=170900,
        mrp_paise=360000,
        available=True,
        url="https://flipkart.com/p/test",
    )
    all_deals = [
        best_deal,
        StoreDeal(store_name="Amazon.in", product_title="Nakpro Perform 1kg", price_paise=208900, available=True, url="https://amazon.in/dp/test1"),
        StoreDeal(store_name="Nakpro Direct", product_title="Nakpro Perform 1kg", price_paise=219900, available=True, url="https://nakpro.com/test2"),
    ]

    purity_cert = purity_service.lookup("Nakpro Perform Whey")
    buy_adv = price_forecaster.evaluate(current_price_paise=170900, mrp_paise=360000)

    png_bytes = deal_card_generator.generate_deal_card(
        product_title="Nakpro Perform Whey Protein 1kg Unflavoured",
        best_deal=best_deal,
        all_deals=all_deals,
        purity_cert=purity_cert,
        buy_advice=buy_adv,
    )

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 20000  # High-definition image
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")  # Valid PNG signature


def test_export_service_csv_document():
    listing = CanonicalListing(
        id=1,
        external_product_id="FK_NAK_01",
        product_title="Nakpro Perform Whey Protein 1kg",
        provider_code="flipkart",
        last_price_paise=170900,
        canonical_url="https://flipkart.com/p/nakpro",
        last_available=True,
    )
    sub = Subscription(
        id=101,
        user_id=12345,
        telegram_id=12345,
        listing_id=1,
        target_price_paise=180000,
    )

    items = [(listing, sub)]
    csv_bytes = export_service.build_csv_document(items)

    assert isinstance(csv_bytes, bytes)
    csv_str = csv_bytes.decode("utf-8")
    assert "Product Name,Store Provider,Current Price (INR)" in csv_str
    assert "Nakpro Perform Whey Protein 1kg" in csv_str
    assert "₹1,709" in csv_str
    assert "₹1,800" in csv_str
    assert "In Stock" in csv_str
    assert "https://flipkart.com/p/nakpro" in csv_str
