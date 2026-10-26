"""Global test configuration and fixtures."""

import pytest
from pricewatch.domain.models import CanonicalListing, PriceQuote


@pytest.fixture
def sample_listing() -> CanonicalListing:
    return CanonicalListing(
        id=1,
        provider_code="shopify:nakpro.com",
        provider_tier=1,
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        pincode="",
        canonical_url="https://nakpro.com/products/impact-whey-protein?variant=40987654321",
        product_title="Nakpro Impact Whey Protein",
        variant_title="1 kg / Chocolate",
        package_quantity="1 kg",
        currency="INR",
        last_price_paise=149900,
        last_mrp_paise=199900,
        last_available=True,
    )


@pytest.fixture
def sample_quote() -> PriceQuote:
    return PriceQuote(
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        price_paise=139900,
        mrp_paise=199900,
        currency="INR",
        available=True,
        verified_pincode="",
        extraction_method="shopify_js",
        seller_name="Nakpro Store",
        raw_variant_title="1 kg / Chocolate",
    )
