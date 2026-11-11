"""Background Market Watch Poller — monitors all major whey brand prices.

Runs every 30 minutes querying multiple stores for flagship whey products from
Nakpro, AS-IT-IS, MuscleBlaze, Avvatar, Nutrabay, Amul, and Optimum Nutrition.
Sends a Telegram alert to users who have opted in (market_watch_enabled=True)
when any product's price drops ≥25% below its MRP.

Design constraints:
- Pure in-process asyncio, no extra infrastructure.
- 6-hour per-user per-product alert cooldown to prevent spam.
- Graceful degradation: store failures are logged and skipped.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from pricewatch.logging_setup import get_logger
from pricewatch.services.link_checker_service import link_checker
from pricewatch.services.protein_validator import (
    estimate_protein_percentage,
    is_quality_whey,
    is_unflavoured_whey,
    is_valid_product_url,
)
from pricewatch.services.store_searchers import query_all_stores

logger = get_logger("market_watch_poller")

# ---------------------------------------------------------------------------
# Brands / queries to monitor — Primary focus: Pure Unflavoured Whey (>=65% protein)
# ---------------------------------------------------------------------------
WATCH_QUERIES: List[str] = [
    # Top preference: Unflavoured / Raw Whey of Major Brands
    "as-it-is whey concentrate 80% unflavoured",
    "as-it-is whey isolate unflavoured",
    "amul raw whey protein concentrate 80%",
    "nakpro platinum whey isolate unflavoured",
    "nakpro gold whey concentrate unflavoured",
    "nutrabay pure raw whey concentrate unflavoured",
    "avvatar 100% whey protein unflavoured",
    "muscleblaze raw whey 80% unflavoured",
    "optimum nutrition gold standard whey unflavoured",
]

# Trigger alert when: (MRP - price) / MRP >= threshold
DISCOUNT_THRESHOLD_PCT: float = 25.0

# Don't re-alert the same (user, product) pair within this window
ALERT_COOLDOWN_SECONDS: int = 6 * 3600  # 6 hours

# In-memory cooldown registry: maps (telegram_id, product_key) -> last_alert_epoch
_last_alerted: Dict[Tuple[int, str], float] = {}


# ---------------------------------------------------------------------------
# Alert formatting
# ---------------------------------------------------------------------------

def _build_alert_text(deal: dict) -> str:
    title = deal.get("title", "Whey Protein Deal")
    price = deal.get("price_inr", 0)
    mrp = deal.get("mrp_inr", 0)
    discount_pct = deal.get("discount_pct", 0)
    store = deal.get("store", "Store")
    url = deal.get("url", "")
    is_unflavoured = deal.get("is_unflavoured", False)
    est_protein_pct = deal.get("protein_pct", 80.0)

    mrp_str = f"<s>₹{mrp:,.0f}</s> " if mrp and mrp > price else ""
    url_part = f'\n\n⚡ <a href="{url}">Buy Now Before It\'s Gone!</a>' if url else ""

    flavour_badge = "🥛 <b>Flavor:</b> Unflavoured / Raw Whey\n" if is_unflavoured else ""
    protein_badge = f"🧪 <b>Verified Protein:</b> ~{est_protein_pct:.0f}% by weight (Quality Whey)\n"

    return (
        "🔥 <b>Market Watch Alert!</b>\n\n"
        f"🛒 <b>{title}</b>\n"
        f"{flavour_badge}"
        f"{protein_badge}"
        f"💰 ₹{price:,.0f} {mrp_str}— <b>{discount_pct:.0f}% OFF</b>\n"
        f"🏪 {store}"
        f"{url_part}\n\n"
        "<i>Turn off with /marketwatch or in /settings</i>"
    )


# ---------------------------------------------------------------------------
# Cooldown helpers
# ---------------------------------------------------------------------------

def _is_cooled_down(telegram_id: int, product_key: str) -> bool:
    """Return True if we have NOT recently alerted this user about this product."""
    key = (telegram_id, product_key)
    last = _last_alerted.get(key)
    if last is None:
        return True
    return (time.monotonic() - last) >= ALERT_COOLDOWN_SECONDS


def _mark_alerted(telegram_id: int, product_key: str) -> None:
    _last_alerted[(telegram_id, product_key)] = time.monotonic()


# ---------------------------------------------------------------------------
# Core poller
# ---------------------------------------------------------------------------

async def _fetch_deals_for_query(query: str) -> List[dict]:
    """Run store search and return deals above the discount threshold."""
    try:
        results = await query_all_stores(query)
    except Exception as exc:
        logger.warning("Market watch store query failed", query=query, error=str(exc))
        return []

    deals: List[dict] = []
    for deal in results:
        if hasattr(deal, "model_dump"):
            deal_data = deal.model_dump()
        elif isinstance(deal, dict):
            deal_data = deal
        else:
            deal_data = {
                "product_title": getattr(deal, "product_title", None) or getattr(deal, "title", None),
                "price_paise": getattr(deal, "price_paise", None) or getattr(deal, "price", None),
                "mrp_paise": getattr(deal, "mrp_paise", None) or getattr(deal, "mrp", None),
                "store_name": getattr(deal, "store_name", None) or getattr(deal, "store", None),
                "url": getattr(deal, "url", None),
            }

        price_paise: Optional[int] = deal_data.get("price_paise") or deal_data.get("price")
        mrp_paise: Optional[int] = deal_data.get("mrp_paise") or deal_data.get("mrp")

        # Normalise: StoreDeals are in paise (e.g., 149900 paise = ₹1,499)
        if price_paise and price_paise > 10_000:
            price_inr = price_paise / 100.0
            mrp_inr = (mrp_paise / 100.0) if mrp_paise else 0.0
        else:
            price_inr = float(price_paise or 0)
            mrp_inr = float(mrp_paise or 0)

        if price_inr <= 0 or mrp_inr <= 0 or mrp_inr <= price_inr:
            continue

        discount_pct = (mrp_inr - price_inr) / mrp_inr * 100.0
        if discount_pct < DISCOUNT_THRESHOLD_PCT:
            continue

        title = deal_data.get("product_title") or deal_data.get("title") or query.title()
        store = deal_data.get("store_name") or deal_data.get("store") or deal_data.get("provider_code") or "Store"
        url = deal_data.get("url") or deal_data.get("canonical_url") or ""
        prod_key = deal_data.get("external_product_id") or url or title

        # Strict Quality Guard: Must be >= 65% protein by weight, exclude cheap Nakpro Impact & mass gainers
        is_ok, reason, est_pct = is_quality_whey(title, min_protein_pct=65.0)
        if not is_ok:
            logger.debug("Market watch filtered out deal", title=title, reason=reason)
            continue

        # Strict URL Guard: Must actually lead directly to a product page, NOT a search query
        if not is_valid_product_url(url):
            logger.debug("Market watch filtered invalid URL", url=url, title=title)
            continue

        is_unflav = is_unflavoured_whey(title)

        deals.append({
            "title": title,
            "price_inr": price_inr,
            "mrp_inr": mrp_inr,
            "discount_pct": discount_pct,
            "store": store,
            "url": url,
            "product_key": prod_key,
            "is_unflavoured": is_unflav,
            "protein_pct": est_pct,
        })

    # In-cycle deduplication by (clean title, store) to avoid spamming multiple identical variant records
    seen_keys = set()
    deduped_deals: List[dict] = []
    for d in deals:
        dedup_key = (d["title"].strip().lower()[:40], d["store"].strip().lower(), round(d["price_inr"]))
        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            deduped_deals.append(d)

    # Sort deals so unflavoured whey appears at the top
    deduped_deals.sort(key=lambda x: (not x.get("is_unflavoured", False), -x.get("discount_pct", 0)))

    # LinkChecker Guard: Verify links are live and drop any quarantined/dead links
    live_deals = await link_checker.filter_live_deals(deduped_deals)
    return live_deals


async def run_market_watch_poller(
    repo: Any,
    bot: Any,
    interval_seconds: int = 1800,
) -> None:
    """
    Continuous background loop polling major whey brands every 30 minutes.

    For every opted-in user, searches all stores for WATCH_QUERIES,
    checks if any deal is ≥25% off MRP, respects a 6-hour per-product
    cooldown, and sends a Telegram alert if conditions are met.
    """
    logger.info(
        "Starting Market Watch background poller",
        interval_seconds=interval_seconds,
        queries=len(WATCH_QUERIES),
        threshold_pct=DISCOUNT_THRESHOLD_PCT,
    )

    while True:
        try:
            # 1. Collect opted-in users
            users = []
            try:
                if hasattr(repo, "get_all_active_users"):
                    all_users = await repo.get_all_active_users()
                    users = [u for u in all_users if getattr(u, "market_watch_enabled", False)]
            except Exception as ue:
                logger.warning("Market watch: could not load users", error=str(ue))

            if not users:
                logger.debug("Market watch: no opted-in users, sleeping")
            else:
                logger.info("Market watch poll cycle starting", opted_in_users=len(users))

                # 2. Fetch deals for all watched queries (parallelised)
                query_tasks = [_fetch_deals_for_query(q) for q in WATCH_QUERIES]
                results = await asyncio.gather(*query_tasks, return_exceptions=True)

                all_deals: List[dict] = []
                for r in results:
                    if isinstance(r, list):
                        all_deals.extend(r)

                logger.info(
                    "Market watch deals found above threshold",
                    deals=len(all_deals),
                    threshold_pct=DISCOUNT_THRESHOLD_PCT,
                )

                # 3. Alert each user for qualifying deals
                for user in users:
                    tg_id = user.telegram_id
                    for deal in all_deals:
                        product_key = deal["product_key"]
                        if not _is_cooled_down(tg_id, product_key):
                            continue
                        try:
                            text = _build_alert_text(deal)
                            await bot.send_message(
                                chat_id=tg_id,
                                text=text,
                                parse_mode="HTML",
                                disable_web_page_preview=False,
                            )
                            _mark_alerted(tg_id, product_key)
                            logger.info(
                                "Market watch alert sent",
                                telegram_id=tg_id,
                                product=deal["title"],
                                discount_pct=round(deal["discount_pct"], 1),
                            )
                            # Friendly broadcast pace: 50ms pause prevents burst floods
                            await asyncio.sleep(0.05)
                        except Exception as send_err:
                            logger.warning(
                                "Failed to send market watch alert",
                                telegram_id=tg_id,
                                product=deal.get("title"),
                                error=str(send_err),
                            )

        except asyncio.CancelledError:
            logger.info("Market Watch poller shutting down.")
            break
        except Exception as exc:
            logger.error("Unexpected error in Market Watch poller loop", error=str(exc))

        jitter = random.uniform(-60.0, 60.0)
        sleep_duration = max(60.0, interval_seconds + jitter)
        logger.debug("Market watch sleeping", seconds=round(sleep_duration))
        await asyncio.sleep(sleep_duration)
