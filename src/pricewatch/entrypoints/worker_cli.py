"""CLI entry point for scheduled GitHub Actions workers."""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pricewatch.config import settings
from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.models import PriceObservation
from pricewatch.logging_setup import get_logger, setup_logging
from pricewatch.repositories.base import BaseListingRepo, BaseSubscriptionRepo
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.repositories.supabase_repo import SupabaseRepository
from pricewatch.services.alert_service import AlertService
from pricewatch.services.check_orchestrator import CheckOrchestrator

logger = get_logger("worker_cli")


def get_default_repository():
    """Retrieve database repository based on settings or fallback to memory."""
    if settings.SUPABASE_URL and (settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN):
        try:
            return SupabaseRepository()
        except Exception as exc:
            logger.warning("Failed to connect to Supabase, falling back to MemoryRepository", error=str(exc))
    return MemoryRepository()


async def run_worker(
    tier: str = "HTTP",
    batch_size: int = 40,
    lease_seconds: int = 300,
) -> int:
    """Run worker check batch for specified tier."""
    worker_id = os.getenv("GITHUB_RUN_ID", f"worker-{uuid.uuid4().hex[:8]}")
    logger.info("Starting PriceWatch worker run", worker_id=worker_id, tier=tier, batch_size=batch_size)

    # Filter tiers
    if tier.upper() == "BROWSER":
        min_tier = ProviderTier.BROWSER.value
        max_tier = ProviderTier.BROWSER.value
    else:
        min_tier = ProviderTier.API_OR_JSON.value
        max_tier = ProviderTier.SCOPED_HTML.value

    repo = get_default_repository()
    orchestrator = CheckOrchestrator()
    alert_service = AlertService(subscription_repo=repo)

    # Claim due listings with atomic lease
    claimed = await repo.claim_due_listings(
        worker_id=worker_id,
        max_tier=max_tier,
        min_tier=min_tier,
        batch_size=batch_size,
        lease_seconds=lease_seconds,
    )

    logger.info(f"Claimed {len(claimed)} due listings for tier {tier}")
    if not claimed:
        logger.info("No listings due for check. Exiting.")
        return 0

    succeeded = 0
    failed = 0
    total_alerts = 0

    for listing in claimed:
        res = await orchestrator.check_listing(listing, median_7d_paise=listing.last_price_paise)
        now = datetime.now(timezone.utc)

        if res.success and res.quote:
            succeeded += 1
            # Record observation if price changed or daily heartbeat
            obs = PriceObservation(
                listing_id=listing.id,
                price_paise=res.quote.price_paise,
                mrp_paise=res.quote.mrp_paise,
                available=res.quote.available,
                seller_name=res.quote.seller_name,
                extraction_method=res.quote.extraction_method,
                is_verified=res.is_verified,
            )
            await repo.record_observation(obs)

            # Evaluate alerts for subscribers
            alerts = await alert_service.process_quote(listing, res.quote)
            total_alerts += alerts

            # Calculate next check interval with adaptive jitter
            next_check = now + timedelta(minutes=settings.DEFAULT_CHECK_INTERVAL_MINUTES)
            await repo.update_listing_state(
                listing_id=listing.id,
                last_price_paise=res.quote.price_paise,
                last_mrp_paise=res.quote.mrp_paise,
                last_available=res.quote.available,
                next_check_at=next_check,
                consecutive_failures=0,
            )
        else:
            failed += 1
            consecutive = listing.consecutive_failures + 1
            backoff_minutes = min(360, settings.DEFAULT_CHECK_INTERVAL_MINUTES * (2 ** min(consecutive, 5)))
            next_check = now + timedelta(minutes=backoff_minutes)

            await repo.update_listing_state(
                listing_id=listing.id,
                last_price_paise=listing.last_price_paise,
                last_mrp_paise=listing.last_mrp_paise,
                last_available=listing.last_available,
                next_check_at=next_check,
                consecutive_failures=consecutive,
                error_code="CHECK_FAILED",
                error_message=res.error or "Unknown error",
            )

    logger.info(
        "Worker execution completed",
        claimed=len(claimed),
        succeeded=succeeded,
        failed=failed,
        alerts_sent=total_alerts,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description="PriceWatch background price check worker.")
    parser.add_argument(
        "--tier",
        choices=["HTTP", "BROWSER"],
        default="HTTP",
        help="Worker tier to execute (HTTP for fast store JSON/LD+JSON, BROWSER for Playwright)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=40,
        help="Max number of listings to claim in this batch",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="Worker database lease lock duration in seconds",
    )
    args = parser.parse_args()

    setup_logging(log_level=settings.LOG_LEVEL)
    exit_code = asyncio.run(
        run_worker(tier=args.tier, batch_size=args.batch_size, lease_seconds=args.lease_seconds)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
