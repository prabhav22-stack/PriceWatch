"""High-frequency background poller for Amul Shop products.

Runs directly inside the Render web process to check active Amul products
every 60 seconds with zero additional server or database costs.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from pricewatch.logging_setup import get_logger
from pricewatch.providers.amul import AmulProvider
from pricewatch.repositories.base import BaseListingRepo, BaseSubscriptionRepo
from pricewatch.services.alert_service import AlertService

logger = get_logger("amul_poller")


async def run_amul_poller(
    repo: Any,
    bot: Any,
    interval_seconds: int = 60,
) -> None:
    """
    Continuous in-memory loop polling active Amul listings every 60 seconds.
    Directly checks StoreHippo REST API (~200ms per SKU) and dispatches instant Telegram restock alerts.
    """
    logger.info("Starting high-frequency Amul background poller...", interval_seconds=interval_seconds)
    provider = AmulProvider()
    alert_service = AlertService(subscription_repo=repo, bot=bot)

    while True:
        try:
            # 1. Fetch all active Amul listings
            listings = await repo.get_active_listings_by_provider("amul")
            if listings:
                logger.info("Fast Amul poller checking active items", count=len(listings))

            for listing in listings:
                try:
                    sku = listing.external_variant_id or listing.external_product_id
                    pincode = listing.pincode or "110001"
                    quote = await provider.fetch_quote(
                        canonical_url=listing.canonical_url,
                        external_product_id=sku,
                        external_variant_id=sku,
                        pincode=pincode,
                    )

                    # Update listing's last recorded inventory & availability
                    await repo.update_listing_state(
                        listing_id=listing.id,
                        last_price_paise=quote.price_paise,
                        last_mrp_paise=quote.mrp_paise,
                        last_available=quote.available,
                        next_check_at=datetime.now(timezone.utc),
                        consecutive_failures=0,
                    )

                    # Evaluate alerts & dispatch Telegram message if restocked
                    await alert_service.process_quote(listing, quote)

                except Exception as exc:
                    logger.warning(
                        "Error checking Amul listing in fast loop",
                        listing_id=listing.id,
                        sku=listing.external_variant_id,
                        error=str(exc),
                    )

        except asyncio.CancelledError:
            logger.info("Amul background poller shutting down.")
            break
        except Exception as exc:
            logger.error("Unexpected error in Amul poller loop", error=str(exc))

        await asyncio.sleep(interval_seconds)
