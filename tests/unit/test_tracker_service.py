"""Unit tests for TrackerService."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from pricewatch.domain.exceptions import PriceWatchError, VariantAmbiguousError
from pricewatch.domain.models import ResolutionResult, VariantOption
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.tracker_service import TrackerService


@pytest.fixture
def tracker_setup():
    repo = MemoryRepository()
    service = TrackerService(
        listing_repo=repo,
        subscription_repo=repo,
        user_repo=repo,
    )
    return service, repo


@pytest.mark.asyncio
async def test_user_registration_and_pincode(tracker_setup):
    service, repo = tracker_setup
    user = await service.get_or_register_user(111222, username="testuser", first_name="Tester")
    assert user.telegram_id == 111222
    assert user.is_active is True

    await service.set_user_pincode(111222, "842002")
    updated = await repo.get_or_create_user(111222)
    assert updated.default_pincode == "842002"


@pytest.mark.asyncio
async def test_track_url_single_variant(tracker_setup):
    service, _ = tracker_setup

    mock_variant = VariantOption(
        external_variant_id="default",
        variant_title="Standard",
        canonical_url="https://example.com/item",
        price_paise=150000,
        mrp_paise=200000,
        available=True,
    )
    mock_resolution = ResolutionResult(
        provider_code="generic:example.com",
        provider_tier=1,
        external_product_id="item-123",
        product_title="Test Item",
        requires_pincode=False,
        variants=[mock_variant],
        pinned_variant_id="default",
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_for_url") as mock_get_p:
        mock_provider = AsyncMock()
        mock_provider.resolve_url.return_value = mock_resolution
        mock_get_p.return_value = mock_provider

        listing, sub = await service.track_url(
            telegram_id=111222,
            url="https://example.com/item",
            target_price_paise=140000,
        )

        assert listing.product_title == "Test Item"
        assert listing.last_price_paise == 150000
        assert sub.target_price_paise == 140000
        assert sub.is_active is True


@pytest.mark.asyncio
async def test_track_url_multi_variant_raises_ambiguous(tracker_setup):
    service, _ = tracker_setup

    v1 = VariantOption(
        external_variant_id="v1",
        variant_title="1kg Chocolate",
        canonical_url="https://example.com/item?v=1",
        price_paise=120000,
        available=True,
    )
    v2 = VariantOption(
        external_variant_id="v2",
        variant_title="2kg Chocolate",
        canonical_url="https://example.com/item?v=2",
        price_paise=220000,
        available=True,
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_for_url") as mock_get_p:
        mock_provider = AsyncMock()
        mock_provider.resolve_url.side_effect = VariantAmbiguousError(
            "Multi-variant", variants=[v1, v2]
        )
        mock_get_p.return_value = mock_provider

        with pytest.raises(VariantAmbiguousError) as exc_info:
            await service.track_url(
                telegram_id=111222,
                url="https://example.com/item",
                target_price_paise=100000,
            )

        assert len(exc_info.value.variants) == 2


@pytest.mark.asyncio
async def test_untrack_product(tracker_setup):
    service, _ = tracker_setup
    mock_variant = VariantOption(
        external_variant_id="default",
        variant_title="Standard",
        canonical_url="https://example.com/item",
        price_paise=150000,
        available=True,
    )
    mock_res = ResolutionResult(
        provider_code="generic:example.com",
        provider_tier=1,
        external_product_id="item-123",
        product_title="Test Item",
        requires_pincode=False,
        variants=[mock_variant],
        pinned_variant_id="default",
    )

    with patch("pricewatch.providers.base.ProviderRegistry.get_provider_for_url") as mock_get_p:
        mock_provider = AsyncMock()
        mock_provider.resolve_url.return_value = mock_res
        mock_get_p.return_value = mock_provider

        listing, sub = await service.track_url(111222, "https://example.com/item", 140000)
        assert len(await service.list_user_subscriptions(111222)) == 1

        # Untrack
        untracked = await service.untrack_product(111222, listing.id)
        assert untracked is True
        assert len(await service.list_user_subscriptions(111222)) == 0
