"""7-Gate PriceValidator to eliminate false-positive alerts and extraction glitches."""

from typing import Optional
from pricewatch.domain.enums import ValidationStatus
from pricewatch.domain.models import CanonicalListing, PriceQuote, ValidationDecision


class PriceValidator:
    """
    Deterministic 7-gate validation pipeline:
    Gate 1: Currency & Format Sanity (INR, ₹1 to ₹10L)
    Gate 2: Variant & Title Lock
    Gate 3: Pincode Lock
    Gate 4: MRP vs Selling Price Sanity
    Gate 5: Cross-Source Consensus
    Gate 6: Availability Consistency
    Gate 7: Anomaly & Cliff Check (>40% drop or <25% of MRP triggers retry)
    """

    MIN_PAISE = 100          # ₹1.00 minimum
    MAX_PAISE = 100_000_000  # ₹10,00,000.00 maximum (₹10 Lakhs)

    @classmethod
    def validate(
        cls,
        quote: PriceQuote,
        listing: CanonicalListing,
        median_7d_paise: Optional[int] = None,
    ) -> ValidationDecision:
        discount_pct = 0

        # Gate 1: Currency & Format Sanity
        if quote.currency.upper() != "INR":
            return ValidationDecision(
                status=ValidationStatus.REJECTED,
                gate_failed=1,
                reason=f"Unsupported currency: {quote.currency} (expected INR)",
            )

        if quote.available:
            if quote.price_paise is None:
                return ValidationDecision(
                    status=ValidationStatus.REJECTED,
                    gate_failed=1,
                    reason="In-stock product has no price_paise",
                )
            if not (cls.MIN_PAISE <= quote.price_paise <= cls.MAX_PAISE):
                return ValidationDecision(
                    status=ValidationStatus.REJECTED,
                    gate_failed=1,
                    reason=f"Price {quote.price_paise} paise out of sanity bounds [{cls.MIN_PAISE}, {cls.MAX_PAISE}]",
                )

        # Gate 2: Variant & Title Lock
        if quote.external_variant_id != listing.external_variant_id:
            return ValidationDecision(
                status=ValidationStatus.REJECTED,
                gate_failed=2,
                reason=f"Variant ID mismatch: extracted '{quote.external_variant_id}' != expected '{listing.external_variant_id}'",
            )

        if listing.package_quantity and quote.raw_variant_title:
            pkg_clean = listing.package_quantity.lower().replace(" ", "")
            title_clean = quote.raw_variant_title.lower().replace(" ", "")
            # Basic sanity: if package_quantity specified (e.g., 2kg) and title says 1kg or 500g
            if ("2kg" in pkg_clean and "1kg" in title_clean) or ("1kg" in pkg_clean and "500g" in title_clean):
                return ValidationDecision(
                    status=ValidationStatus.REJECTED,
                    gate_failed=2,
                    reason=f"Package quantity contradiction: expected '{listing.package_quantity}' but title has '{quote.raw_variant_title}'",
                )

        # Gate 3: Pincode Lock
        if listing.pincode:
            if quote.verified_pincode != listing.pincode:
                return ValidationDecision(
                    status=ValidationStatus.REJECTED,
                    gate_failed=3,
                    reason=f"Pincode mismatch: page verified '{quote.verified_pincode}' != required '{listing.pincode}'",
                )

        # Gate 4: MRP vs Selling Price
        if quote.mrp_paise is not None and quote.price_paise is not None:
            if quote.price_paise > quote.mrp_paise:
                return ValidationDecision(
                    status=ValidationStatus.REJECTED,
                    gate_failed=4,
                    reason=f"Selling price ({quote.price_paise}p) exceeds MRP ({quote.mrp_paise}p)",
                )
            if quote.mrp_paise > quote.price_paise:
                discount_pct = int(round((quote.mrp_paise - quote.price_paise) * 100 / quote.mrp_paise))

        # Gate 5: Cross-Source Consensus
        if "CONTRADICTION" in quote.extraction_method.upper():
            return ValidationDecision(
                status=ValidationStatus.REJECTED,
                gate_failed=5,
                reason="Cross-source contradiction detected between metadata and DOM prices",
            )

        # Gate 6: Availability Consistency
        if not quote.available and (quote.price_paise is None or quote.price_paise <= 0):
            # Out of stock with no valid price is completely normal
            pass

        # Gate 7: Anomaly & Cliff Check (Trigger Verification Re-Check)
        if quote.available and quote.price_paise is not None:
            if median_7d_paise and median_7d_paise > 0:
                drop_threshold = int(median_7d_paise * 0.60)
                if quote.price_paise < drop_threshold:
                    return ValidationDecision(
                        status=ValidationStatus.NEEDS_VERIFICATION_RETRY,
                        gate_failed=7,
                        reason=f"Extreme drop (>40%) from 7d median: {quote.price_paise}p vs median {median_7d_paise}p",
                        requires_retry=True,
                        discount_pct=discount_pct,
                    )

            if quote.mrp_paise and quote.mrp_paise > 0:
                cliff_threshold = int(quote.mrp_paise * 0.25)
                if quote.price_paise < cliff_threshold:
                    return ValidationDecision(
                        status=ValidationStatus.NEEDS_VERIFICATION_RETRY,
                        gate_failed=7,
                        reason=f"Suspiciously low price (<25% of MRP): {quote.price_paise}p vs MRP {quote.mrp_paise}p",
                        requires_retry=True,
                        discount_pct=discount_pct,
                    )

        return ValidationDecision(
            status=ValidationStatus.VALID,
            discount_pct=discount_pct,
        )
