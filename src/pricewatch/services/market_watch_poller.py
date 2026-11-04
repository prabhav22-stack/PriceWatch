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
from pricewatch.services.store_searchers import query_all_stores

logger = get_logger("market_watch_poller")

# ---------------------------------------------------------------------------
# Brands / queries to monitor
# ---------------------------------------------------------------------------
WATCH_QUERIES: List[str] = [
    "nakpro whey protein",
    "as-it-is whey protein",
    "muscleblaze biozyme whey",
    "avvatar whey protein",
    "nutrabay whey protein",
    "amul whey protein",
    "optimum nutrition gold standard whey",
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

    mrp_str = f"<s>₹{mrp:,.0f}</s> " if mrp and mrp > price else ""
    url_part = f'\n\n⚡ <a href="{url}">Buy Now Before It\'s Gone!</a>' if url else ""

    return (
        "🔥 <b>Market Watch Alert!</b>\n\n"
        f"🛒 <b>{title}</b>\n"
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
        price_paise: Optional[int] = deal.get("price_paise") or deal.get("price")
        mrp_paise: Optional[int] = deal.get("mrp_paise") or deal.get("mrp")

        # Normalise: some store_searchers return rupee floats, others paise ints
        if price_paise and price_paise > 50_000:
            # likely paise — convert
            price_inr = price_paise / 100
            mrp_inr = (mrp_paise / 100) if mrp_paise else 0
        else:
            price_inr = float(price_paise or 0)
            mrp_inr = float(mrp_paise or 0)

        if price_inr <= 0 or mrp_inr <= 0 or mrp_inr <= price_inr:
            continue

        discount_pct = (mrp_inr - price_inr) / mrp_inr * 100
        if discount_pct < DISCOUNT_THRESHOLD_PCT:
            continue

        deals.append({
            "title": deal.get("title") or deal.get("product_title") or query.title(),
            "price_inr": price_inr,
            "mrp_inr": mrp_inr,
            "discount_pct": discount_pct,
            "store": deal.get("store") or deal.get("provider_code") or "Store",
            "url": deal.get("url") or deal.get("canonical_url") or "",
            "product_key": deal.get("external_product_id") or deal.get("url") or query,
        })

    return deals


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
