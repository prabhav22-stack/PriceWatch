"""High-frequency background batch poller for Amul Shop products.

Runs directly inside the Render web process to check the entire Amul protein catalog
every 60 seconds using StoreHippo's batch category endpoint (~200ms for all 24 items).
Supports instant restock alerts for explicitly tracked products, starred favourites,
and 'all protein' subscribers with zero Redis or BullMQ overhead.
"""

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, List, Set

from pricewatch.domain.models import CanonicalListing, PriceQuote, Subscription, User
from pricewatch.logging_setup import get_logger
from pricewatch.providers.amul import AmulProvider
from pricewatch.services.alert_service import AlertService
from pricewatch.services.amul_stock_tracker import AmulStockTracker

logger = get_logger("amul_poller")


async def run_amul_poller(
    repo: Any,
    bot: Any,
    interval_seconds: int = 60,
) -> None:
    """
    Continuous in-memory loop polling Amul catalog every 60 seconds.
    Fetches the entire protein category in a single batch API call (~200ms) for each registered user pincode.
    Automatically updates real-time warehouse inventory and dispatches instant Telegram restock alerts.
    """
    logger.info("Starting high-frequency Amul background batch poller...", interval_seconds=interval_seconds)
    provider = AmulProvider()
    alert_service = AlertService(subscription_repo=repo, bot=bot, user_repo=repo)

    while True:
        try:
            # 1. Fetch active listings and registered users to collect all unique pincodes
            active_amul_listings = await repo.get_active_listings_by_provider("amul")
            pincodes: Set[str] = set()
            for l in active_amul_listings:
                if l.pincode and len(str(l.pincode).strip()) == 6:
                    pincodes.add(str(l.pincode).strip())

            users: List[User] = []
            try:
                if hasattr(repo, "get_all_active_users"):
                    users = await repo.get_all_active_users()
            except Exception as u_err:
                logger.warning("Could not fetch active users in poller", error=str(u_err))

            for u in users:
                pin = u.default_pincode
                if pin and len(str(pin).strip()) == 6:
                    pincodes.add(str(pin).strip())

            if not pincodes:
                pincodes.add("842002")

            # 3. Batch check Amul catalog for each pincode
            for pincode in pincodes:
                try:
                    category_items = await provider.fetch_category_products(
                        category_id="protein", pincode=pincode, limit=100
                    )
                    substore = await provider.resolve_substore_for_pincode(pincode)

                    relevant_users = [
                        u for u in users
                        if (u.default_pincode and u.default_pincode.strip() == pincode) or len(users) == 1
                    ]
                    if not relevant_users and users:
                        relevant_users = users

                    processed_skus: Set[str] = set()

                    for item in category_items:
                        sku = item.get("sku")
                        if not sku:
                            continue
                        processed_skus.add(sku)

                        is_avail = bool(item.get("available", False))
                        eff_qty = item.get("inventory_quantity")
                        price_paise = item.get("price_paise")
                        if price_paise is not None and price_paise <= 0:
                            price_paise = None
                        mrp_paise = item.get("mrp_paise")
                        if mrp_paise is not None and mrp_paise <= 0:
                            mrp_paise = None
                        name = item.get("name") or sku
                        alias = item.get("alias") or sku
                        clean_alias = alias.replace(" ", "") if alias else sku
                        url = item.get("url") or f"https://shop.amul.com/en/product/{clean_alias}"

                        quote = PriceQuote(
                            external_product_id=sku,
                            external_variant_id=sku,
                            price_paise=price_paise,
                            mrp_paise=mrp_paise,
                            currency="INR",
                            available=is_avail,
                            inventory_quantity=eff_qty,
                            verified_pincode=pincode,
                            extraction_method="amul_storehippo_batch",
                            raw_variant_title=name,
                        )

                        # Get or create listing in database
                        new_listing = CanonicalListing(
                            provider_code="amul",
                            provider_tier=1,
                            external_product_id=sku,
                            external_variant_id=sku,
                            pincode=pincode,
                            canonical_url=url,
                            product_title=name,
                            variant_title="Standard Pack",
                            currency="INR",
                            last_price_paise=price_paise,
                            last_mrp_paise=mrp_paise,
                            last_available=is_avail,
                            inventory_quantity=eff_qty,
                            is_monitored=True,
                        )
                        listing = await repo.get_or_create_listing(new_listing)

                        # Update real-time listing state
                        await repo.update_listing_state(
                            listing_id=listing.id,
                            last_price_paise=price_paise,
                            last_mrp_paise=mrp_paise,
                            last_available=is_avail,
                            next_check_at=datetime.now(timezone.utc),
                            consecutive_failures=0,
                            canonical_url=url,
                        )

                        # Update stock history transition tracking
                        try:
                            AmulStockTracker.get_instance().record_observation(
                                sku=sku,
                                substore=substore,
                                is_available=is_avail,
                            )
                        except Exception as hist_err:
                            logger.warning("Failed updating stock tracker history in batch poller", error=str(hist_err))

                        # Evaluate active user subscriptions for this listing
                        await alert_service.process_quote(listing, quote)

                    # Also check any standalone monitored Amul listings outside the category
                    active_amul_listings = await repo.get_active_listings_by_provider("amul")
                    for l in active_amul_listings:
                        sku = l.external_variant_id or l.external_product_id
                        if sku not in processed_skus:
                            try:
                                q = await provider.fetch_quote(
                                    l.canonical_url, sku, sku, pincode=l.pincode or pincode
                                )
                                await repo.update_listing_state(
                                    listing_id=l.id,
                                    last_price_paise=q.price_paise,
                                    last_mrp_paise=q.mrp_paise,
                                    last_available=q.available,
                                    next_check_at=datetime.now(timezone.utc),
                                    consecutive_failures=0,
                                )
                                await alert_service.process_quote(l, q)
                            except Exception as standalone_err:
                                logger.warning("Error checking standalone Amul listing", sku=sku, error=str(standalone_err))

                except Exception as batch_err:
                    logger.warning("Failed batch checking Amul category for pincode", pincode=pincode, error=str(batch_err))

        except asyncio.CancelledError:
            logger.info("Amul background poller shutting down.")
            break
        except Exception as exc:
            logger.error("Unexpected error in Amul poller loop", error=str(exc))

        jitter = random.uniform(-4.0, 4.0)
        sleep_duration = max(5.0, interval_seconds + jitter)
        await asyncio.sleep(sleep_duration)
