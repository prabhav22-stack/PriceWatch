"""Unit tests for headless ChartService price history generator."""

from datetime import datetime, timedelta, timezone

from pricewatch.domain.models import CanonicalListing, PriceObservation
from pricewatch.services.chart_service import ChartService


def test_chart_generation_empty_observations_fallback_to_last_price():
    listing = CanonicalListing(
        id=101,
        provider_code="amazon",
        provider_tier=1,
        external_product_id="B07WZM3714",
        external_variant_id="B07WZM3714",
        pincode="110001",
        canonical_url="https://amazon.in/dp/B07WZM3714",
        product_title="Optimum Nutrition Gold Standard Whey 1kg",
        variant_title="Double Rich Chocolate",
        currency="INR",
        last_price_paise=329900,
        last_mrp_paise=389900,
        last_available=True,
    )

    chart_bytes = ChartService.generate_price_history_chart(
        listing=listing,
        observations=[],
        target_price_paise=300000,
    )

    assert chart_bytes is not None
    assert len(chart_bytes) > 1000
    # PNG signature check: \x89PNG\r\n\x1a\n
    assert chart_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_generation_with_fluctuating_observations():
    listing = CanonicalListing(
        id=102,
        provider_code="shopify:nakpro.com",
        provider_tier=1,
        external_product_id="nakpro-gold",
        external_variant_id="1kg-unflavoured",
        pincode="110001",
        canonical_url="https://nakpro.com/products/nakpro-gold",
        product_title="Nakpro Gold Whey Isolate 1kg",
        variant_title="Unflavoured",
        currency="INR",
        last_price_paise=210000,
        last_mrp_paise=269900,
        last_available=True,
    )

    now = datetime.now(timezone.utc)
    observations = [
        PriceObservation(
            listing_id=102,
            price_paise=240000,
            available=True,
            extraction_method="api",
            observed_at=now - timedelta(days=3),
        ),
        PriceObservation(
            listing_id=102,
            price_paise=225000,
            available=True,
            extraction_method="api",
            observed_at=now - timedelta(days=2),
        ),
        PriceObservation(
            listing_id=102,
            price_paise=199900,  # All-time low
            available=True,
            extraction_method="api",
            observed_at=now - timedelta(days=1),
        ),
        PriceObservation(
            listing_id=102,
            price_paise=210000,
            available=True,
            extraction_method="api",
            observed_at=now,
        ),
    ]

    chart_bytes = ChartService.generate_price_history_chart(
        listing=listing,
        observations=observations,
        target_price_paise=200000,
    )

    assert chart_bytes is not None
    assert len(chart_bytes) > 5000
    assert chart_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_generation_returns_none_when_no_data():
    listing = CanonicalListing(
        id=103,
        provider_code="amazon",
        provider_tier=1,
        external_product_id="B000",
        external_variant_id="B000",
        pincode="110001",
        canonical_url="https://amazon.in/dp/B000",
        product_title="Missing Product",
        variant_title="Default",
        currency="INR",
        last_price_paise=None,
        last_mrp_paise=None,
        last_available=False,
    )

    chart_bytes = ChartService.generate_price_history_chart(
        listing=listing,
        observations=[],
    )

    assert chart_bytes is None
