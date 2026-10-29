"""Unit tests for the 7-Gate PriceValidator."""

import pytest
from pricewatch.domain.enums import ValidationStatus
from pricewatch.domain.models import CanonicalListing, PriceQuote
from pricewatch.validation.price_validator import PriceValidator


def test_validator_accepts_clean_quote(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    decision = PriceValidator.validate(sample_quote, sample_listing, median_7d_paise=145000)
    assert decision.status == ValidationStatus.VALID
    assert decision.discount_pct == 30  # (199900 - 139900) / 199900 = ~30%


def test_gate1_rejects_non_inr_currency(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    bad_quote = sample_quote.model_copy(update={"currency": "USD"})
    decision = PriceValidator.validate(bad_quote, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 1
    assert "Unsupported currency" in (decision.reason or "")


def test_gate1_rejects_out_of_bounds_price(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    # Less than 100 paise (₹1)
    too_low = sample_quote.model_copy(update={"price_paise": 50})
    decision = PriceValidator.validate(too_low, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 1

    # Greater than ₹10 Lakhs (100,000,000 paise)
    too_high = sample_quote.model_copy(update={"price_paise": 200_000_000})
    decision = PriceValidator.validate(too_high, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 1


def test_gate2_rejects_variant_mismatch(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    wrong_variant = sample_quote.model_copy(update={"external_variant_id": "99999999"})
    decision = PriceValidator.validate(wrong_variant, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 2
    assert "Variant ID mismatch" in (decision.reason or "")


def test_gate2_rejects_package_quantity_contradiction(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    contradicting_listing = sample_listing.model_copy(update={"package_quantity": "2 kg"})
    contradicting_quote = sample_quote.model_copy(update={"raw_variant_title": "Impact Whey 1kg Chocolate"})
    decision = PriceValidator.validate(contradicting_quote, contradicting_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 2
    assert "Package quantity contradiction" in (decision.reason or "")


def test_gate3_rejects_pincode_mismatch(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    pincode_listing = sample_listing.model_copy(update={"pincode": "842002"})
    wrong_pincode_quote = sample_quote.model_copy(update={"verified_pincode": "400001"})
    decision = PriceValidator.validate(wrong_pincode_quote, pincode_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 3
    assert "Pincode mismatch" in (decision.reason or "")


def test_gate3_allows_nationwide_provider_without_verified_pincode(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    # Nutrabay or Shopify listing has user default pincode, but nationwide store returns empty verified_pincode
    nutrabay_listing = sample_listing.model_copy(update={"provider_code": "nutrabay", "pincode": "842002"})
    nationwide_quote = sample_quote.model_copy(update={"verified_pincode": ""})
    decision = PriceValidator.validate(nationwide_quote, nutrabay_listing)
    assert decision.status == ValidationStatus.VALID


def test_gate3_rejects_amazon_fresh_missing_verified_pincode(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    # Amazon Fresh strictly requires verified pincode
    fresh_listing = sample_listing.model_copy(update={"provider_code": "amazon_fresh", "pincode": "560001"})
    fresh_quote = sample_quote.model_copy(update={"verified_pincode": ""})
    decision = PriceValidator.validate(fresh_quote, fresh_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 3
    assert "Pincode verification required" in (decision.reason or "")


def test_gate4_rejects_mrp_inversion(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    # Selling price ₹2,500 > MRP ₹1,999
    inverted_quote = sample_quote.model_copy(update={"price_paise": 250000, "mrp_paise": 199900})
    decision = PriceValidator.validate(inverted_quote, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 4
    assert "exceeds MRP" in (decision.reason or "")


def test_gate4_zero_discount_when_selling_equals_mrp(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    equal_quote = sample_quote.model_copy(update={"price_paise": 199900, "mrp_paise": 199900})
    decision = PriceValidator.validate(equal_quote, sample_listing)
    assert decision.status == ValidationStatus.VALID
    assert decision.discount_pct == 0


def test_gate5_rejects_cross_source_contradiction(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    contradiction_quote = sample_quote.model_copy(update={"extraction_method": "CONTRADICTION_JSONLD_DOM"})
    decision = PriceValidator.validate(contradiction_quote, sample_listing)
    assert decision.status == ValidationStatus.REJECTED
    assert decision.gate_failed == 5


def test_gate6_accepts_out_of_stock_with_none_price(sample_quote: PriceQuote, sample_listing: CanonicalListing):
    oos_quote = sample_quote.model_copy(update={"available": False, "price_paise": None})
    decision = PriceValidator.validate(oos_quote, sample_listing)
    assert decision.status == ValidationStatus.VALID


def test_gate7_triggers_retry_on_extreme_drop_from_median(
    sample_quote: PriceQuote, sample_listing: CanonicalListing
):
    # Median is ₹1,500 (150000 paise). 40% drop threshold is ₹900.
    # New quote is ₹800 (80000 paise) -> extreme drop
    flash_drop_quote = sample_quote.model_copy(update={"price_paise": 80000})
    decision = PriceValidator.validate(flash_drop_quote, sample_listing, median_7d_paise=150000)
    assert decision.status == ValidationStatus.NEEDS_VERIFICATION_RETRY
    assert decision.gate_failed == 7
    assert decision.requires_retry is True
    assert "Extreme drop" in (decision.reason or "")


def test_gate7_triggers_retry_on_suspiciously_low_price_vs_mrp(
    sample_quote: PriceQuote, sample_listing: CanonicalListing
):
    # MRP is ₹2,000 (200000 paise). 25% threshold is ₹500.
    # New quote is ₹300 (30000 paise) -> < 25% of MRP
    suspicious_quote = sample_quote.model_copy(update={"price_paise": 30000, "mrp_paise": 200000})
    decision = PriceValidator.validate(suspicious_quote, sample_listing, median_7d_paise=None)
    assert decision.status == ValidationStatus.NEEDS_VERIFICATION_RETRY
    assert decision.gate_failed == 7
    assert decision.requires_retry is True
    assert "Suspiciously low price" in (decision.reason or "")
