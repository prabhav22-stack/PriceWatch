"""Unit tests for protein validator, quality filter, and product URL verification."""

import pytest
from pricewatch.services.protein_validator import (
    estimate_protein_percentage,
    is_quality_whey,
    is_unflavoured_whey,
    is_valid_product_url,
)


def test_is_unflavoured_whey_detection():
    assert is_unflavoured_whey("AS-IT-IS Nutrition Whey Concentrate 80% Raw Unflavoured") is True
    assert is_unflavoured_whey("Amul Raw Whey Protein Concentrate 80%") is True
    assert is_unflavoured_whey("Nakpro Platinum 100% Whey Isolate", "Unflavoured") is True
    assert is_unflavoured_whey("Nutrabay Pure Raw Whey 80% Plain") is True

    # Flavoured wheys should be False
    assert is_unflavoured_whey("Nakpro Gold Whey Concentrate", "Malai Kulfi") is False
    assert is_unflavoured_whey("MuscleBlaze Biozyme Performance Whey Double Rich Chocolate") is False


def test_estimate_protein_percentage():
    assert estimate_protein_percentage("AS-IT-IS Whey Concentrate 80%") == 80.0
    assert estimate_protein_percentage("Nakpro Platinum 100% Whey Isolate Unflavoured") == 90.0
    assert estimate_protein_percentage("Amul Raw Whey Protein 80%") == 80.0
    # Ratio parsing: 24g protein per 30g scoop -> 80%
    assert estimate_protein_percentage("Whey Protein 24g protein per 30g scoop") == 80.0
    # Nakpro Impact should be estimated ~50%
    assert estimate_protein_percentage("Nakpro Impact Whey Protein") == 50.0


def test_is_quality_whey_filters_nakpro_impact_and_mass_gainers():
    # 1. Nakpro Impact Whey is explicitly rejected
    is_ok, reason, pct = is_quality_whey("Nakpro Impact Whey Protein Chocolate")
    assert is_ok is False
    assert "Excluded" in reason or "below" in reason

    # 2. Mass gainers are rejected
    is_ok, reason, _ = is_quality_whey("MuscleBlaze Super Gainer XXL Mass Gainer")
    assert is_ok is False

    # 3. Nutrabay Vital Whey (~60% protein) is rejected (< 65%)
    is_ok, reason, _ = is_quality_whey("Nutrabay Gold Vital Whey Protein for Beginners")
    assert is_ok is False

    # 4. Pure Raw Whey Concentrate 80% passes (> 65%)
    is_ok, reason, pct = is_quality_whey("AS-IT-IS Nutrition Whey Concentrate 80% Raw Unflavoured")
    assert is_ok is True
    assert pct >= 65.0

    # 5. Amul Raw Whey passes
    is_ok, reason, pct = is_quality_whey("Amul Raw Whey Protein Concentrate 80%")
    assert is_ok is True
    assert pct >= 65.0

    # 6. Nakpro Platinum Isolate passes
    is_ok, reason, pct = is_quality_whey("Nakpro Platinum 100% Whey Isolate Unflavoured")
    assert is_ok is True
    assert pct >= 85.0


def test_is_valid_product_url():
    # Valid product URLs
    assert is_valid_product_url("https://www.amazon.in/dp/B07X2QKVXH") is True
    assert is_valid_product_url("https://www.flipkart.com/as-it-is-nutrition-one-whey-protein/p/itm54fcb09cd7346") is True
    assert is_valid_product_url("https://shop.amul.com/en/product/amul-whey-protein-32-g-or-pack-of-30-sachets") is True
    assert is_valid_product_url("https://nutrabay.com/product/nutrabay-whey-protein-concentrate") is True
    assert is_valid_product_url("https://nakpro.com/products/nakpro-whey-isolate-protein-powder-unflavored") is True
    assert is_valid_product_url("https://www.healthkart.com/sv/nakpro-impact-whey-protein/SP-122819?navKey=VRNT-234019") is True

    # Broken or search query URLs MUST be rejected
    assert is_valid_product_url("https://www.amazon.in/s?k=whey+protein") is False
    assert is_valid_product_url("https://www.flipkart.com/search?q=whey") is False
    assert is_valid_product_url("https://nutrabay.com/search?q=whey") is False
    assert is_valid_product_url("https://www.healthkart.com/search?txtQ=whey") is False
    assert is_valid_product_url("https://shop.amul.com/en/browse/protein") is False
    assert is_valid_product_url("") is False
    assert is_valid_product_url("not_a_url") is False
