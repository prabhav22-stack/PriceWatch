"""Check orchestrator with bounded concurrency and two-stage verification."""

import asyncio
from typing import Optional
from dataclasses import dataclass

from pricewatch.domain.enums import ValidationStatus
from pricewatch.domain.exceptions import PriceWatchError
from pricewatch.domain.models import CanonicalListing, PriceQuote, ValidationDecision
from pricewatch.logging_setup import get_logger
from pricewatch.providers.base import ProviderRegistry
from pricewatch.validation.price_validator import PriceValidator

logger = get_logger("orchestrator")


@dataclass
class CheckResult:
    listing_id: Optional[int]
    quote: Optional[PriceQuote]
    decision: Optional[ValidationDecision]
    is_verified: bool
    success: bool
    error: Optional[str] = None


class CheckOrchestrator:
    """Coordinates provider fetching, price validation, and two-stage verification."""

    def __init__(self, max_concurrency: int = 5, retry_delay_seconds: float = 0.5):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.retry_delay_seconds = retry_delay_seconds

    async def check_listing(
        self,
        listing: CanonicalListing,
        median_7d_paise: Optional[int] = None,
    ) -> CheckResult:
        """Execute price check for a canonical listing with validation and verification."""
        async with self.semaphore:
            try:
                # 1. Resolve Provider
                try:
                    provider = ProviderRegistry.get_provider_by_code(listing.provider_code)
                except ValueError:
                    provider = ProviderRegistry.get_provider_for_url(listing.canonical_url)

                # 2. Fetch Initial Quote
                quote = await provider.fetch_quote(
                    canonical_url=listing.canonical_url,
                    external_product_id=listing.external_product_id,
                    external_variant_id=listing.external_variant_id,
                    pincode=listing.pincode,
                )

                # 3. Validate Quote
                decision = PriceValidator.validate(
                    quote=quote,
                    listing=listing,
                    median_7d_paise=median_7d_paise,
                )

                # 4. Two-Stage Verification for Extreme Drops (>40% drop / <25% of MRP)
                is_verified = True
                if decision.status == ValidationStatus.NEEDS_VERIFICATION_RETRY:
                    logger.info(
                        "Extreme drop detected; triggering verification re-check",
                        listing_id=listing.id,
                        price_paise=quote.price_paise,
                        reason=decision.reason,
                    )
                    await asyncio.sleep(self.retry_delay_seconds)
                    try:
                        second_quote = await provider.fetch_quote(
                            canonical_url=listing.canonical_url,
                            external_product_id=listing.external_product_id,
                            external_variant_id=listing.external_variant_id,
                            pincode=listing.pincode,
                        )
                        # Verify that the second quote confirms the price and variant
                        if (
                            second_quote.price_paise == quote.price_paise
                            and second_quote.external_variant_id == quote.external_variant_id
                            and second_quote.available == quote.available
                        ):
                            logger.info(
                                "Extreme price drop verified successfully",
                                listing_id=listing.id,
                                verified_price=second_quote.price_paise,
                            )
                            # Accepted as verified drop!
                            decision = ValidationDecision(
                                status=ValidationStatus.VALID,
                                discount_pct=decision.discount_pct,
                                reason="Extreme drop confirmed by two-stage verification",
                            )
                            is_verified = True
                        else:
                            logger.warning(
                                "Verification re-check disagreed; rejecting check",
                                listing_id=listing.id,
                                initial_price=quote.price_paise,
                                second_price=second_quote.price_paise,
                            )
                            return CheckResult(
                                listing_id=listing.id,
                                quote=second_quote,
                                decision=ValidationDecision(
                                    status=ValidationStatus.REJECTED,
                                    gate_failed=7,
                                    reason="Verification re-check disagreed with initial reading",
                                ),
                                is_verified=False,
                                success=False,
                                error="Verification disagreement",
                            )
                    except Exception as verify_exc:
                        logger.error(
                            "Verification re-check failed with error",
                            listing_id=listing.id,
                            error=str(verify_exc),
                        )
                        return CheckResult(
                            listing_id=listing.id,
                            quote=quote,
                            decision=ValidationDecision(
                                status=ValidationStatus.REJECTED,
                                gate_failed=7,
                                reason=f"Verification re-check error: {verify_exc}",
                            ),
                            is_verified=False,
                            success=False,
                            error=str(verify_exc),
                        )

                if decision.status == ValidationStatus.REJECTED:
                    return CheckResult(
                        listing_id=listing.id,
                        quote=quote,
                        decision=decision,
                        is_verified=False,
                        success=False,
                        error=decision.reason,
                    )

                return CheckResult(
                    listing_id=listing.id,
                    quote=quote,
                    decision=decision,
                    is_verified=is_verified,
                    success=True,
                )

            except PriceWatchError as pw_err:
                logger.error("PriceWatch error during check", listing_id=listing.id, error=str(pw_err))
                return CheckResult(
                    listing_id=listing.id,
                    quote=None,
                    decision=None,
                    is_verified=False,
                    success=False,
                    error=str(pw_err),
                )
            except Exception as exc:
                logger.exception("Unexpected error during check", listing_id=listing.id, error=str(exc))
                return CheckResult(
                    listing_id=listing.id,
                    quote=None,
                    decision=None,
                    is_verified=False,
                    success=False,
                    error=str(exc),
                )
