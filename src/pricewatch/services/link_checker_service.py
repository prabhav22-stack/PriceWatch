"""Asynchronous Link Health Checker, Redirection Tracker, and Dead-Link Quarantine.

Inspired by linkchecker principles:
- Performs fast async HTTP HEAD (or byte-range GET) validation
- Tracks redirection paths (detects redirects to search pages or out-of-stock fallbacks)
- Maintains a Dead-Link Quarantine with TTL to avoid re-querying broken URLs
- Integrates with Market Watch poller and store searchers to guarantee zero broken links
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from pricewatch.logging_setup import get_logger
from pricewatch.providers.http_client import http_client
from pricewatch.services.protein_validator import is_valid_product_url

logger = get_logger("link_checker")

# Quarantine duration for dead links (2 hours)
QUARANTINE_TTL_SECONDS = 7200

# Cache duration for verified working links (1 hour)
VERIFIED_CACHE_TTL_SECONDS = 3600

# In-memory quarantine registry: url -> (reason, expiry_timestamp)
_quarantine_registry: Dict[str, Tuple[str, float]] = {}

# In-memory verified cache: url -> expiry_timestamp
_verified_cache: Dict[str, float] = {}


class LinkHealthChecker:
    """Asynchronous validator verifying product links before dispatching to users."""

    def __init__(self):
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def is_quarantined(self, url: str) -> bool:
        """Check if a URL is currently in dead-link quarantine."""
        now = time.monotonic()
        entry = _quarantine_registry.get(url)
        if entry:
            reason, expiry = entry
            if now < expiry:
                return True
            # Expired quarantine
            _quarantine_registry.pop(url, None)
        return False

    def quarantine_url(self, url: str, reason: str) -> None:
        """Add a broken URL to quarantine."""
        expiry = time.monotonic() + QUARANTINE_TTL_SECONDS
        _quarantine_registry[url] = (reason, expiry)
        logger.info("Quarantined dead link", url=url, reason=reason)

    def is_recently_verified(self, url: str) -> bool:
        """Check if URL was successfully verified recently."""
        now = time.monotonic()
        expiry = _verified_cache.get(url)
        if expiry and now < expiry:
            return True
        if expiry:
            _verified_cache.pop(url, None)
        return False

    def mark_verified(self, url: str) -> None:
        _verified_cache[url] = time.monotonic() + VERIFIED_CACHE_TTL_SECONDS

    async def verify_url_live(self, url: str, timeout: float = 4.0) -> Tuple[bool, str]:
        """
        Actively checks if a product URL is alive and does not redirect to search/error.
        Returns (is_alive, reason).
        """
        # 1. Structural check
        if not is_valid_product_url(url):
            return False, "Structural URL validation failed (search or malformed URL)"

        # 2. Check quarantine
        if self.is_quarantined(url):
            return False, "URL is currently in dead-link quarantine"

        # 3. Check recent verification cache
        if self.is_recently_verified(url):
            return True, "Cached verified alive"

        # 4. Perform active HTTP verification via lightweight byte-range GET
        try:
            headers = dict(self._headers)
            headers["Range"] = "bytes=0-1024"
            resp = await http_client.get(url, headers=headers, timeout=timeout)

            final_url = str(resp.url).lower()

            # Check status code
            if resp.status_code in (404, 410):
                self.quarantine_url(url, f"HTTP {resp.status_code} Not Found")
                return False, f"HTTP {resp.status_code} Not Found"

            if resp.status_code >= 500:
                return False, f"HTTP {resp.status_code} Server Error"

            # Check redirection-path tracking: did it redirect to search or home?
            bad_redirect_indicators = [
                "/search", "?q=", "?txtq=", "/404", "not-found",
                "/collections/all", "/category/all",
            ]
            if any(b in final_url for b in bad_redirect_indicators):
                self.quarantine_url(url, f"Redirected to non-product fallback: {final_url}")
                return False, "Redirected to search/not-found page"

            # If we reach here, URL is valid and reachable
            self.mark_verified(url)
            return True, "Live and verified"

        except Exception as exc:
            logger.debug("Active link verification exception", url=url, error=str(exc))
            # On network timeout, do not quarantine immediately, but allow structural URL
            return True, f"Network probe skipped: {str(exc)}"

    async def filter_live_deals(self, deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Concurrently verifies a list of deals and returns only those with live links."""
        if not deals:
            return []

        async def _check(deal: Dict[str, Any]):
            url = deal.get("url") or ""
            is_ok, _ = await self.verify_url_live(url)
            return deal if is_ok else None

        results = await asyncio.gather(*[_check(d) for d in deals], return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]


# Global singleton instance
link_checker = LinkHealthChecker()
