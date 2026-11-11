"""CLI entry point for scheduled GitHub Actions workers."""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pricewatch.config import get_provider_check_interval, settings
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
    worker_id: Optional[str] = None,
) -> int:
    """Run worker check batch for specified tier."""
    worker_id = worker_id or os.getenv("GITHUB_RUN_ID", f"worker-{uuid.uuid4().hex[:8]}")
    logger.info("Starting PriceWatch worker run", worker_id=worker_id, tier=tier, batch_size=batch_size)

    # Filter tiers
    t = tier.upper()
    if t in ("BROWSER", "TIER_4"):
        min_tier = ProviderTier.BROWSER.value
        max_tier = ProviderTier.BROWSER.value
    elif t in ("TIER_3", "SCOPED_HTML"):
        min_tier = ProviderTier.SCOPED_HTML.value
        max_tier = ProviderTier.BROWSER.value
    elif t == "ALL":
        min_tier = ProviderTier.API_OR_JSON.value
        max_tier = ProviderTier.BROWSER.value
    else:  # HTTP
        min_tier = ProviderTier.API_OR_JSON.value
        max_tier = ProviderTier.SCOPED_HTML.value

    repo = get_default_repository()
    orchestrator = CheckOrchestrator()
    alert_service = AlertService(subscription_repo=repo, listing_repo=repo)

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
    provider_consecutive_blocks: dict[str, int] = {}

    for listing in claimed:
        # Check if provider circuit breaker is currently tripped in this run
        if provider_consecutive_blocks.get(listing.provider_code, 0) >= 3:
            logger.warning(
                "Skipping listing due to tripped provider circuit breaker",
                provider=listing.provider_code,
                listing_id=listing.id,
            )
            # Push check into the future by 30 mins + jitter
            import random
            trip_backoff = timedelta(minutes=30 + random.randint(1, 15))
            await repo.update_listing_state(
                listing_id=listing.id,
                last_price_paise=listing.last_price_paise,
                last_mrp_paise=listing.last_mrp_paise,
                last_available=listing.last_available,
                next_check_at=datetime.now(timezone.utc) + trip_backoff,
                consecutive_failures=listing.consecutive_failures + 1,
                error_code="CIRCUIT_BREAKER_TRIPPED",
                error_message="Provider circuit breaker tripped due to 3+ consecutive bot blocks/rate limits",
            )
            failed += 1
            continue

        res = await orchestrator.check_listing(listing, median_7d_paise=listing.last_price_paise)
        now = datetime.now(timezone.utc)

        if res.success and res.quote:
            succeeded += 1
            provider_consecutive_blocks[listing.provider_code] = 0
            # Record observation only if price, MRP, or availability changed, or if no previous price recorded (prevents table bloat)
            state_changed = (
                listing.last_price_paise != res.quote.price_paise
                or listing.last_mrp_paise != res.quote.mrp_paise
                or listing.last_available != res.quote.available
                or listing.last_price_paise is None
            )
            if state_changed:
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

            # Calculate next check interval with tiered provider frequency
            interval_td = get_provider_check_interval(listing.provider_code)
            next_check = now + interval_td
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

            # Detect bot blocks, rate limits, or anti-scraping challenges
            err_msg = res.error or "Unknown error"
            is_bot_or_limit = any(k in err_msg.lower() for k in ("bot", "robot", "captcha", "403", "429", "blocked"))
            if is_bot_or_limit:
                current_blocks = provider_consecutive_blocks.get(listing.provider_code, 0) + 1
                provider_consecutive_blocks[listing.provider_code] = current_blocks
                if current_blocks >= 3:
                    logger.warning(
                        "Trip circuit breaker for provider: 3+ consecutive bot blocks or rate limits",
                        provider=listing.provider_code,
                    )

            interval_td = get_provider_check_interval(listing.provider_code)
            base_minutes = max(1, int(interval_td.total_seconds() // 60))
            if is_bot_or_limit:
                # Minimum 30 minutes backoff + jitter for bot blocks
                import random
                backoff_minutes = max(30, base_minutes * (2 ** min(consecutive, 5))) + random.randint(1, 15)
            else:
                backoff_minutes = min(360, base_minutes * (2 ** min(consecutive, 5)))
            next_check = now + timedelta(minutes=backoff_minutes)

            await repo.update_listing_state(
                listing_id=listing.id,
                last_price_paise=listing.last_price_paise,
                last_mrp_paise=listing.last_mrp_paise,
                last_available=listing.last_available,
                next_check_at=next_check,
                consecutive_failures=consecutive,
                error_code="BOT_BLOCKED" if is_bot_or_limit else "CHECK_FAILED",
                error_message=err_msg,
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
        default="HTTP",
        help="Worker tier to execute (HTTP, BROWSER, TIER_3, TIER_4, ALL)",
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
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Unique worker identifier string",
    )
    args = parser.parse_args()

    setup_logging(log_level=settings.LOG_LEVEL)
    exit_code = asyncio.run(
        run_worker(
            tier=args.tier,
            batch_size=args.batch_size,
            lease_seconds=args.lease_seconds,
            worker_id=args.worker_id,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
