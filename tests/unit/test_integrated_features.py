"""Unit tests for integrated advanced capabilities:

- Holman's Spark Unicode sparkline generator
- Amazon-Buddy Deal Intelligence & Fake Discount Detector
- Datasketch MinHash LSH semantic matching
- Crawlee resilient anti-bot fetcher
- Multiplatform vision OCR fallback
"""

import pytest
from pricewatch.services.sparkline import generate_sparkline, format_price_trend_summary
from pricewatch.services.deal_intelligence import deal_intelligence
from pricewatch.services.minhash_matcher import ProductCatalogLSHIndex, compute_minhash_jaccard
from pricewatch.services.crawlee_scraper import crawlee_fetcher
from pricewatch.services.vision_extractor import vision_extractor


def test_sparkline_generator():
    """Verify sparklines correctly scale and render Unicode block levels."""
    vals = [100, 200, 300, 400, 500, 600, 700, 800]
    spark = generate_sparkline(vals)
    assert len(spark) == 8
    assert spark[0] == " "
    assert spark[-1] == "█"

    # Flat values
    flat = generate_sparkline([50, 50, 50])
    assert len(flat) == 3


def test_format_price_trend_summary():
    """Verify trend summary indicates direction and detects all-time lows."""
    # Dropping trend with ATL
    prices_paise = [250000, 240000, 230000, 210000, 199900]
    summary = format_price_trend_summary(prices_paise)
    assert summary is not None
    assert "Dropping" in summary
    assert "All-Time Low!" in summary
    assert "1,999" in summary


def test_deal_intelligence_fair_deal():
    """Verify normal competitive deal scoring."""
    score = deal_intelligence.evaluate_deal(
        selling_price_paise=208900,
        mrp_paise=249900,
        all_store_prices_paise=[208900, 219900, 229900],
    )
    assert score.score >= 5.0
    assert not score.is_fake_discount
    assert score.verdict in ("👍 FAIR PRICE", "⚡ GREAT DEAL", "🔥 STEAL DEAL")


def test_deal_intelligence_fake_discount_detection():
    """Verify detection of artificially inflated MRP."""
    score = deal_intelligence.evaluate_deal(
        selling_price_paise=200000,
        mrp_paise=550000,  # 175% higher than market median!
        all_store_prices_paise=[200000, 210000, 220000],
    )
    assert score.is_fake_discount is True
    assert score.verdict == "⚠️ INFLATED MRP"
    assert "inflated" in score.summary.lower()


def test_deal_intelligence_steal_deal():
    """Verify detection of high-discount steal deals."""
    score = deal_intelligence.evaluate_deal(
        selling_price_paise=120000,
        mrp_paise=240000,
        all_store_prices_paise=[200000, 210000, 220000],
        lowest_historical_paise=130000,
    )
    assert score.score >= 8.0
    assert "STEAL DEAL" in score.verdict or "GREAT DEAL" in score.verdict


def test_minhash_lsh_indexing_and_query():
    """Verify MinHash LSH indexes and queries catalog products."""
    idx = ProductCatalogLSHIndex(threshold=0.20)
    idx.index_product("nakpro_1", "Nakpro Perform Whey Protein Concentrate 1kg Unflavoured")
    idx.index_product("nutrabay_1", "Nutrabay Pure Shilajit Resin 20g")
    idx.index_product("amul_1", "Amul High Protein Lassi 200ml")

    matches = idx.query_similar("Nakpro Perform Whey 1kg")
    assert len(matches) > 0
    top_match = matches[0]
    assert top_match[0] == "nakpro_1"
    assert top_match[1] > 0.20

    # Near-zero similarity for unrelated item
    j_unrelated = compute_minhash_jaccard("Nakpro Whey", "Amul Lassi Rose")
    assert j_unrelated < 0.15


def test_crawlee_fetcher_initialization():
    """Verify crawlee fetcher singleton is initialized and has fetch_html method."""
    assert hasattr(crawlee_fetcher, "fetch_html")


def test_vision_extractor_multiplatform_ocr():
    """Verify vision extractor has _extract_via_local_ocr loaded."""
    assert hasattr(vision_extractor, "_extract_via_local_ocr")
