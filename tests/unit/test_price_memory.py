"""Unit tests for 30-day Price Memory and Significant Discount Alerts (strictly non-Amul)."""

from datetime import datetime, timedelta, timezone
import pytest

from pricewatch.domain.enums import AlertType
from pricewatch.domain.models import CanonicalListing, PriceObservation, PriceQuote, Subscription
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.alert_service import AlertService


@pytest.fixture
def memory_repo_with_history():
    repo = MemoryRepository()
    now = datetime.now(timezone.utc)

    # Add a non-Amul listing (e.g. Nakpro Impact Whey)
    listing = repo.listings[10] = CanonicalListing(
        id=10,
        provider_code="shopify:nakpro.com",
        external_product_id="nakpro-whey",
        external_variant_id="v1",
        canonical_url="https://nakpro.com/products/nakpro-whey",
        product_title="Nakpro Platinum Whey 1kg",
        last_price_paise=220000,  # Rs. 2200
    )

    # Add Amul listing
    amul_listing = repo.listings[20] = CanonicalListing(
        id=20,
        provider_code="amul",
        external_product_id="amul-protein-lassi",
        external_variant_id="amul-lassi-sku",
        canonical_url="https://shop.amul.com/product/amul-lassi",
        product_title="Amul High Protein Lassi",
        last_price_paise=2500,
    )

    # Add 30 days of price observations for listing 10
    # Prices over past 30 days: 2200, 2100, 2300, 2250, 2200
    history_prices = [220000, 210000, 230000, 225000, 220000]
    for idx, price in enumerate(history_prices):
        obs_time = now - timedelta(days=25 - (idx * 5))
        repo.observations.append(
            PriceObservation(
                id=idx + 1,
                listing_id=10,
                price_paise=price,
                observed_at=obs_time,
                available=True,
                extraction_method="test",
            )
        )

    # Add an old observation (> 30 days ago) that must be filtered out
    repo.observations.append(
        PriceObservation(
            id=99,
            listing_id=10,
            price_paise=999999,  # Rs. 9999.99
            observed_at=now - timedelta(days=45),
            available=True,
            extraction_method="test",
        )
    )

    return repo, listing, amul_listing


@pytest.mark.asyncio
async def test_30d_price_summary_aggregation(memory_repo_with_history):
    repo, listing, _ = memory_repo_with_history

    summary = await repo.get_30d_price_summary(listing.id)
    assert summary is not None
    assert summary["count"] == 5
    assert summary["min_price"] == 210000  # Rs. 2100
    assert summary["max_price"] == 230000  # Rs. 2300
    assert summary["median_price"] == 220000  # Rs. 2200
    assert summary["avg_price"] == (220000 + 210000 + 230000 + 225000 + 220000) // 5


@pytest.mark.asyncio
async def test_30d_price_summary_empty():
    repo = MemoryRepository()
    summary = await repo.get_30d_price_summary(999)
    assert summary is None


def test_significant_discount_below_median(memory_repo_with_history):
    _, listing, _ = memory_repo_with_history
    summary = {
        "min_price": 210000,
        "max_price": 230000,
        "median_price": 220000,  # Rs. 2200
        "avg_price": 221000,
        "count": 5,
    }

    # User target is Rs. 1800 (180000 paise) - not reached yet
    sub = Subscription(
        id=1,
        telegram_id=123456,
        listing_id=listing.id,
        target_price_paise=180000,
        alert_rearmed=True,
    )

    # Current price drops to Rs. 1950 (195000 paise)
    # 1950 is ~11.36% below the 2200 median (>= 10% discount threshold)
    quote = PriceQuote(
        external_product_id="nakpro-whey",
        external_variant_id="v1",
        price_paise=195000,
        available=True,
        extraction_method="test",
    )

    alert = AlertService.evaluate_alert(
        sub=sub,
        quote=quote,
        listing=listing,
        price_summary_30d=summary,
    )

    assert alert == AlertType.SIGNIFICANT_DROP


def test_minor_discount_does_not_trigger_significant_drop(memory_repo_with_history):
    _, listing, _ = memory_repo_with_history
    summary = {
        "min_price": 210000,
        "max_price": 230000,
        "median_price": 220000,  # Rs. 2200
        "avg_price": 221000,
        "count": 5,
    }

    sub = Subscription(
        id=1,
        telegram_id=123456,
        listing_id=listing.id,
        target_price_paise=180000,
        alert_rearmed=True,
    )

    # Current price is Rs. 2150 (only 2.2% below 2200 median, above target 1800)
    quote = PriceQuote(
        external_product_id="nakpro-whey",
        external_variant_id="v1",
        price_paise=215000,
        available=True,
        extraction_method="test",
    )

    alert = AlertService.evaluate_alert(
        sub=sub,
        quote=quote,
        listing=listing,
        price_summary_30d=summary,
    )

    assert alert is None


def test_amul_strictly_bypasses_price_memory(memory_repo_with_history):
    _, _, amul_listing = memory_repo_with_history

    sub = Subscription(
        id=2,
        telegram_id=123456,
        listing_id=amul_listing.id,
        target_price_paise=2000,
        alert_rearmed=True,
    )

    # Amul quote with price dropped by 50%
    quote = PriceQuote(
        external_product_id="amul-protein-lassi",
        external_variant_id="amul-lassi-sku",
        price_paise=1200,
        available=True,
        inventory_quantity=15,
        extraction_method="rest",
    )

    # Even if price_summary_30d is provided, Amul must NOT trigger SIGNIFICANT_DROP.
    # It only triggers AMUL_RESTOCK for stock/availability.
    alert = AlertService.evaluate_alert(
        sub=sub,
        quote=quote,
        listing=amul_listing,
        price_summary_30d={"median_price": 2500, "min_price": 2400, "max_price": 2600},
    )

    assert alert == AlertType.AMUL_RESTOCK
    assert alert != AlertType.SIGNIFICANT_DROP


def test_format_alert_message_with_30d_memory(memory_repo_with_history):
    _, listing, _ = memory_repo_with_history
    summary = {
        "min_price": 200000,
        "max_price": 240000,
        "median_price": 220000,
        "avg_price": 220000,
        "count": 10,
    }

    sub = Subscription(
        id=1,
        telegram_id=123456,
        listing_id=listing.id,
        target_price_paise=180000,
        alert_rearmed=True,
    )

    # Case 1: 30-day low
    quote_low = PriceQuote(
        external_product_id="nakpro-whey",
        external_variant_id="v1",
        price_paise=190000,  # Below min 200000
        available=True,
        extraction_method="test",
    )

    msg = AlertService.format_alert_message(
        alert_type=AlertType.SIGNIFICANT_DROP,
        quote=quote_low,
        listing=listing,
        sub=sub,
        price_summary_30d=summary,
    )

    assert "LOWEST PRICE IN 30 DAYS!" in msg
    assert "30-Day Memory:" in msg
    assert "30-Day Range:" in msg
    assert "Open Store Link" in msg
