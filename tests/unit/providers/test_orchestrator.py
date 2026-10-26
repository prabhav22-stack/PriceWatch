"""Unit tests for CheckOrchestrator and Two-Stage Verification."""

from unittest.mock import AsyncMock, patch
import pytest

from pricewatch.domain.enums import ValidationStatus
from pricewatch.domain.models import CanonicalListing, PriceQuote
from pricewatch.services.check_orchestrator import CheckOrchestrator


@pytest.fixture
def test_listing():
    return CanonicalListing(
        id=42,
        provider_code="shopify:nakpro.com",
        provider_tier=1,
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        pincode="",
        canonical_url="https://nakpro.com/products/impact-whey-protein?variant=40987654321",
        product_title="Nakpro Whey",
        last_price_paise=150000,
        last_mrp_paise=200000,
    )


@pytest.mark.asyncio
async def test_orchestrator_standard_check(test_listing):
    mock_quote = PriceQuote(
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        price_paise=145000,
        mrp_paise=200000,
        currency="INR",
        available=True,
        extraction_method="shopify_js",
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_by_code") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.fetch_quote.return_value = mock_quote
        mock_get_provider.return_value = mock_provider

        orchestrator = CheckOrchestrator()
        result = await orchestrator.check_listing(test_listing, median_7d_paise=150000)

        assert result.success is True
        assert result.is_verified is True
        assert result.quote.price_paise == 145000
        assert result.decision.status == ValidationStatus.VALID


@pytest.mark.asyncio
async def test_orchestrator_two_stage_verification_confirmed(test_listing):
    # Median is 150000 (Rs 1500). Flash price is 80000 (Rs 800) -> >40% drop
    flash_quote = PriceQuote(
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        price_paise=80000,
        mrp_paise=200000,
        currency="INR",
        available=True,
        extraction_method="shopify_js",
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_by_code") as mock_get_provider:
        mock_provider = AsyncMock()
        # Both initial and verification check return the same flash drop price
        mock_provider.fetch_quote.side_effect = [flash_quote, flash_quote]
        mock_get_provider.return_value = mock_provider

        orchestrator = CheckOrchestrator(retry_delay_seconds=0.01)
        result = await orchestrator.check_listing(test_listing, median_7d_paise=150000)

        assert mock_provider.fetch_quote.call_count == 2
        assert result.success is True
        assert result.is_verified is True
        assert result.decision.status == ValidationStatus.VALID
        assert "Extreme drop confirmed" in (result.decision.reason or "")


@pytest.mark.asyncio
async def test_orchestrator_two_stage_verification_disagreed(test_listing):
    # Initial quote reports glitch drop to Rs 500
    glitch_quote = PriceQuote(
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        price_paise=50000,
        mrp_paise=200000,
        currency="INR",
        available=True,
        extraction_method="shopify_js",
    )
    # Second check returns normal price Rs 1500
    normal_quote = PriceQuote(
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
        price_paise=150000,
        mrp_paise=200000,
        currency="INR",
        available=True,
        extraction_method="shopify_js",
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_by_code") as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.fetch_quote.side_effect = [glitch_quote, normal_quote]
        mock_get_provider.return_value = mock_provider

        orchestrator = CheckOrchestrator(retry_delay_seconds=0.01)
        result = await orchestrator.check_listing(test_listing, median_7d_paise=150000)

        assert mock_provider.fetch_quote.call_count == 2
        assert result.success is False
        assert result.is_verified is False
        assert result.decision.status == ValidationStatus.REJECTED
