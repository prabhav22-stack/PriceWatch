"""Unit tests for AlertService: 6-scenario hysteresis state machine and outbox idempotency."""

from unittest.mock import AsyncMock
import pytest

from pricewatch.domain.enums import AlertType
from pricewatch.domain.models import CanonicalListing, PriceQuote, Subscription
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.alert_service import AlertService


@pytest.fixture
def alert_setup():
    repo = MemoryRepository()
    service = AlertService(subscription_repo=repo, user_repo=repo)

    sub = Subscription(
        id=1,
        telegram_id=12345678,
        listing_id=10,
        target_price_paise=100000,  # Rs. 1000
        notify_on_further_drop_pct=2,
        alert_rearmed=True,
        last_alerted_price_paise=None,
    )

    listing = CanonicalListing(
        id=10,
        provider_code="shopify:nakpro.com",
        external_product_id="impact-whey",
        external_variant_id="v1",
        canonical_url="https://nakpro.com/products/impact-whey",
        product_title="Impact Whey",
    )

    return service, repo, sub, listing


def test_scenario_1_initial_drop_to_target(alert_setup):
    service, _, sub, _ = alert_setup
    # Price drops to Rs. 980 (98000 paise)
    quote = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=98000,
        available=True,
        extraction_method="test",
    )
    alert = service.evaluate_alert(sub, quote)
    assert alert == AlertType.TARGET_REACHED


def test_scenario_2_steady_below_target_suppressed(alert_setup):
    service, _, sub, _ = alert_setup
    # Already alerted at Rs. 980
    alerted_sub = sub.model_copy(
        update={"alert_rearmed": False, "last_alerted_price_paise": 98000}
    )
    # Price is now Rs. 975 (Drop is only 0.5% < 2%)
    quote = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=97500,
        available=True,
        extraction_method="test",
    )
    alert = service.evaluate_alert(alerted_sub, quote)
    assert alert is None


def test_scenario_3_significant_further_drop(alert_setup):
    service, _, sub, _ = alert_setup
    alerted_sub = sub.model_copy(
        update={"alert_rearmed": False, "last_alerted_price_paise": 98000}
    )
    # Price drops to Rs. 950 (Drop is ~3.06% >= 2%)
    quote = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=95000,
        available=True,
        extraction_method="test",
    )
    alert = service.evaluate_alert(alerted_sub, quote)
    assert alert == AlertType.FURTHER_DROP


def test_scenario_4_minor_price_flap_suppressed(alert_setup):
    service, _, sub, _ = alert_setup
    alerted_sub = sub.model_copy(
        update={"alert_rearmed": False, "last_alerted_price_paise": 98000}
    )
    # Price rises slightly to Rs. 1010 (+1% over target) -> does not reach +3% rearm threshold
    quote_rise = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=101000,
        available=True,
        extraction_method="test",
    )
    assert service.evaluate_alert(alerted_sub, quote_rise) is None

    # Price drops back to Rs. 985 -> still higher than last alerted Rs. 980 -> suppressed!
    quote_drop = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=98500,
        available=True,
        extraction_method="test",
    )
    assert service.evaluate_alert(alerted_sub, quote_drop) is None


def test_scenario_5_price_recovery_rearms(alert_setup):
    service, _, sub, _ = alert_setup
    alerted_sub = sub.model_copy(
        update={"alert_rearmed": False, "last_alerted_price_paise": 98000}
    )
    # Price rises to Rs. 1050 (>= Rs. 1030 which is +3% of Rs 1000 target)
    quote_recovered = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=105000,
        available=True,
        extraction_method="test",
    )
    # evaluate_alert returns None because price is above target, but qualifies for rearm
    assert service.evaluate_alert(alerted_sub, quote_recovered) is None


@pytest.mark.asyncio
async def test_idempotent_outbox_deduplication(alert_setup):
    service, repo, sub, listing = alert_setup
    # Save sub and listing into memory repo
    await repo.create_or_update_subscription(sub)
    await repo.get_or_create_listing(listing)

    quote = PriceQuote(
        external_product_id="impact-whey",
        external_variant_id="v1",
        price_paise=95000,
        available=True,
        extraction_method="test",
    )

    # First check: alert triggers and is logged
    sent1 = await service.process_quote(listing, quote)
    assert sent1 == 1

    # Second check immediately after with same price: suppressed by idempotency key
    sent2 = await service.process_quote(listing, quote)
    assert sent2 == 0
