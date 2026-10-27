"""Amul Shop (StoreHippo) provider with real-time stock and inventory tracking.

Inherently mirrors the API architecture and provisions of:
https://github.com/SwapnilSoni1999/amul-notify
"""

import asyncio
import hashlib
import json
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.exceptions import ExtractionError
from pricewatch.domain.models import PriceQuote, ResolutionResult, VariantOption
from pricewatch.logging_setup import get_logger
from pricewatch.providers.base import BaseProvider, ProviderRegistry
from pricewatch.validation.normalizer import parse_inr_to_paise

logger = get_logger("amul_provider")

STORE_ID = "62fa94df8c13af2e242eba16"
SHOP_URL = "https://shop.amul.com"

# Default categories mirrored from amul-notify
AMUL_CATEGORIES = [
    {"id": "protein", "emoji": "💪", "label": "Protein"},
    {"id": "chocolates", "emoji": "🍫", "label": "Chocolates"},
    {"id": "organic", "emoji": "🌱", "label": "Organic"},
    {"id": "ghee", "emoji": "🧈", "label": "Ghee"},
    {"id": "milk", "emoji": "🥛", "label": "Milk"},
]

DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,hi;q=0.8",
    "base_url": "https://shop.amul.com/en/browse/protein",
    "cache-control": "no-cache",
    "frontend": "1",
    "pragma": "no-cache",
    "referer": "https://shop.amul.com/en/browse/protein",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


@ProviderRegistry.register
class AmulProvider(BaseProvider):
    """Tier 1 StoreHippo stock and inventory provider for Amul Shop."""

    provider_code = "amul"
    tier = ProviderTier.API_OR_JSON

    def __init__(self):
        self._session_tid: Optional[str] = None
        self._cookies: Dict[str, str] = {}
        self._session_created_at: float = 0
        self._pincode_substore_cache: Dict[str, str] = {}

    @classmethod
    def can_handle(cls, url: str) -> bool:
        domain = (urlparse(url).hostname or "").lower()
        return "shop.amul.com" in domain or "amul.com" in domain

    @staticmethod
    def calculate_tid_header(session_tid: str) -> str:
        """StoreHippo dynamic HMAC-SHA256 TID signature computation."""
        timestamp = str(int(time.time() * 1000))
        rand = str(int(random.random() * 1000))
        raw = f"{STORE_ID}:{timestamp}:{rand}:{session_tid}"
        sig = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{timestamp}:{rand}:{sig}"

    async def _ensure_session(self, client: httpx.AsyncClient) -> str:
        """Establish valid cookies and StoreHippo session TID."""
        now = time.time()
        # Sessions expire after ~15 minutes
        if self._session_tid and (now - self._session_created_at < 600):
            return self._session_tid

        logger.info("Initializing fresh Amul StoreHippo session...")
        # 1. Acquire cookies
        r1 = await client.get(f"{SHOP_URL}/en/browse/protein")
        # 2. Extract TID
        r2 = await client.get(f"{SHOP_URL}/user/info.js?_v={int(now * 1000)}")
        match = re.search(r"session\s*=\s*(\{.*?\});", r2.text) or re.search(r"session\s*=\s*(\{.*\})", r2.text)
        if not match:
            raise ExtractionError("Failed to extract session TID from Amul user/info.js")

        s_data = json.loads(match.group(1))
        tid = s_data.get("tid")
        if not tid:
            raise ExtractionError("Amul session info missing TID")

        self._session_tid = tid
        self._session_created_at = now
        return tid

    def invalidate_session(self) -> None:
        """Force session TID refresh on next API request."""
        self._session_tid = None
        self._session_created_at = 0

    async def get_substore_for_pincode(self, pincode: str, client: httpx.AsyncClient) -> str:
        """Resolve delivery pincode to internal Amul warehouse/substore alias."""
        clean_pin = pincode.strip()
        if clean_pin in self._pincode_substore_cache:
            return self._pincode_substore_cache[clean_pin]

        tid = await self._ensure_session(client)
        tid_hdr = self.calculate_tid_header(tid)
        headers = {**DEFAULT_HEADERS, "tid": tid_hdr}

        url = f"{SHOP_URL}/entity/pincode?limit=50&filters[0][field]=pincode&filters[0][value]={clean_pin}&filters[0][operator]=regex&cf_cache=1h"
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning("Pincode lookup returned non-200", status=resp.status_code, pincode=clean_pin)
            return "delhi"  # sensible fallback

        data = resp.json()
        records = data.get("records", []) or data.get("data", [])
        if not records:
            logger.warning("No substore found for pincode", pincode=clean_pin)
            return "delhi"

        substore = records[0].get("substore", "delhi")
        self._pincode_substore_cache[clean_pin] = substore
        return substore

    async def resolve_substore_for_pincode(self, pincode: str) -> str:
        """Convenience method to resolve substore for a pincode using an internal HTTP client."""
        clean_pin = pincode.strip()
        if clean_pin in self._pincode_substore_cache:
            return self._pincode_substore_cache[clean_pin]
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0) as client:
            return await self.get_substore_for_pincode(clean_pin, client)

    async def set_substore_preference(self, substore: str, client: httpx.AsyncClient) -> None:
        """Notify StoreHippo session of active delivery substore."""
        tid = await self._ensure_session(client)
        tid_hdr = self.calculate_tid_header(tid)
        headers = {**DEFAULT_HEADERS, "tid": tid_hdr}
        pref_url = f"{SHOP_URL}/entity/ms.settings/_/setPreferences"
        await client.put(pref_url, json={"data": {"store": substore}}, headers=headers)

    @staticmethod
    def calculate_effective_inventory(item: Dict[str, Any]) -> Tuple[bool, int]:
        """
        Calculate true purchase availability and available stock units.
        Directly mirrors vendor/amul-notify/src/utils/amul.util.ts
        """
        raw_allow = item.get("inventory_allow_out_of_stock", "0")
        allow_oos = raw_allow not in ("0", 0, False, "false", "False", None)
        if allow_oos:
            return True, int(item.get("inventory_quantity", 999) or 999)

        raw_avail = item.get("available", 0)
        is_avail_flag = bool(raw_avail) and raw_avail not in (0, "0", False, "false", "False")
        if not is_avail_flag:
            return False, 0

        qty = int(item.get("inventory_quantity", 0) or 0)
        low_qty = int(item.get("inventory_low_stock_quantity", 0) or 0)

        eff_qty = max(0, qty - low_qty)
        if qty < low_qty or eff_qty <= 0:
            return False, 0
        return True, eff_qty

    @staticmethod
    def extract_protein_info(item: Dict[str, Any]) -> str:
        """
        Extract protein content string directly from StoreHippo product metafields benefits.
        Directly mirrors vendor/amul-notify/src/utils/format.util.ts
        """
        metafields = item.get("metafields") or {}
        benefits = metafields.get("benefits", "") if isinstance(metafields, dict) else ""
        protein_regex = r"<li>[^<]*?(\d+(?:\.\d+)?)(?:\s*(g|kg|mg|%))?[^<]*?\b[Pp]rotein\b.*?</li>"
        match = re.search(protein_regex, benefits, re.IGNORECASE)
        if match:
            raw = match.group(0)
            return raw.replace("<li>", "").replace("</li>", "").replace("&nbsp;", " ").strip()

        sku = item.get("sku", "")
        if sku in ("BTMCP11_30", "BTMCP11"):
            return "15g protein"
        return "N/A"

    async def fetch_category_products(
        self, category_id: str = "protein", pincode: str = "110001", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch all products in an Amul category with live inventory for a pincode."""
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0) as client:
            substore = await self.get_substore_for_pincode(pincode, client)
            await self.set_substore_preference(substore, client)

            tid = await self._ensure_session(client)
            tid_hdr = self.calculate_tid_header(tid)
            headers = {**DEFAULT_HEADERS, "tid": tid_hdr}

            query = (
                f"filters[0][field]=categories&filters[0][value][0]={category_id}&filters[0][operator]=in"
                f"&filters[0][original]=1&limit={limit}&start=0&v=6"
            )
            url = f"{SHOP_URL}/api/1/entity/ms.products?{query}"
            resp = await client.get(url, headers=headers)
            if resp.status_code in (401, 403):
                logger.warning("Amul session expired (HTTP 401/403), re-establishing session...", status=resp.status_code)
                self.invalidate_session()
                tid = await self._ensure_session(client)
                headers = {**DEFAULT_HEADERS, "tid": self.calculate_tid_header(tid)}
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                raise ExtractionError(f"HTTP {resp.status_code} fetching Amul category {category_id}")

            data = resp.json()
            items = data.get("data", [])
            results = []
            for item in items:
                is_avail, eff_qty = self.calculate_effective_inventory(item)
                images = item.get("images", [])
                image_url = None
                if images and isinstance(images, list) and isinstance(images[0], str):
                    image_url = f"https://shop.amul.com{images[0]}" if not images[0].startswith("http") else images[0]

                alias = item.get("alias", "")
                clean_alias = alias.replace(" ", "") if alias else (item.get("sku") or "")
                prod_url = f"{SHOP_URL}/en/product/{clean_alias}" if clean_alias else SHOP_URL

                results.append({
                    "sku": item.get("sku"),
                    "name": item.get("name"),
                    "alias": alias,
                    "url": prod_url,
                    "price_paise": parse_inr_to_paise(str(item.get("price", "0"))),
                    "mrp_paise": parse_inr_to_paise(str(item.get("compare_price", "0"))),
                    "available": is_avail,
                    "inventory_quantity": eff_qty,
                    "image_url": image_url,
                    "substore": substore,
                    "protein": self.extract_protein_info(item),
                    "metafields": item.get("metafields"),
                })
            return results

    async def search_products(
        self, query: str, pincode: str = "842002", categories: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Search products across categories matching a keyword or fuzzy string."""
        cats = categories or ["protein", "dairy", "chocolates", "bakery"]
        all_products: List[Dict[str, Any]] = []
        seen_skus = set()
        for cat in cats:
            try:
                cat_prods = await self.fetch_category_products(cat, pincode=pincode, limit=100)
                for p in cat_prods:
                    sku = p.get("sku")
                    if sku and sku not in seen_skus:
                        seen_skus.add(sku)
                        all_products.append(p)
            except Exception as e:
                logger.warning("Error fetching category for search", cat=cat, error=str(e))

        clean_query = query.strip()
        if not clean_query:
            return all_products

        pattern = re.compile(".*?".join(map(re.escape, clean_query)), re.IGNORECASE)
        matches = [
            p for p in all_products
            if pattern.search(p.get("name", ""))
            or pattern.search(p.get("sku", ""))
            or pattern.search(p.get("alias", ""))
            or pattern.search(p.get("protein", ""))
        ]
        return matches

    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        """Resolve a direct shop.amul.com product URL during onboarding."""
        effective_pin = pincode or "110001"
        parsed = urlparse(url)
        # Extract alias or SKU from path: e.g. /en/browse/product/<alias>
        parts = [p for p in parsed.path.split("/") if p]
        alias = parts[-1] if parts else ""

        # Fetch matching product from StoreHippo
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0) as client:
            substore = await self.get_substore_for_pincode(effective_pin, client)
            await self.set_substore_preference(substore, client)

            tid = await self._ensure_session(client)
            tid_hdr = self.calculate_tid_header(tid)
            headers = {**DEFAULT_HEADERS, "tid": tid_hdr}

            query = (
                f"filters[0][field]=alias&filters[0][value]={alias}&filters[0][operator]=equal"
                "&fields[name]=1&fields[sku]=1&fields[price]=1&fields[compare_price]=1"
                "&fields[available]=1&fields[inventory_quantity]=1&fields[inventory_low_stock_quantity]=1"
                "&fields[inventory_allow_out_of_stock]=1&limit=1"
            )
            url_api = f"{SHOP_URL}/api/1/entity/ms.products?{query}"
            resp = await client.get(url_api, headers=headers)
            items = resp.json().get("data", []) if resp.status_code == 200 else []

            if not items:
                # If alias lookup fails, create clean generic option with SKU/alias
                product_title = alias.replace("-", " ").title()
                sku = alias
                price_paise = None
                available = False
                eff_qty = 0
            else:
                it = items[0]
                product_title = it.get("name", alias.title())
                sku = it.get("sku", alias)
                price_paise = parse_inr_to_paise(str(it.get("price", "0")))
                available, eff_qty = self.calculate_effective_inventory(it)

            clean_alias = alias.replace(" ", "") if alias else sku
            canonical_url = f"{SHOP_URL}/en/product/{clean_alias}" if clean_alias else SHOP_URL
            variant = VariantOption(
                external_variant_id=sku,
                variant_title="Standard Pack",
                canonical_url=canonical_url,
                price_paise=price_paise,
                available=available,
                inventory_quantity=eff_qty,
            )

            return ResolutionResult(
                provider_code=self.provider_code,
                provider_tier=self.tier,
                external_product_id=sku,
                product_title=product_title,
                requires_pincode=True,
                variants=[variant],
                pinned_variant_id=sku,
            )

    async def fetch_quote(
        self,
        canonical_url: str,
        external_product_id: str,
        external_variant_id: str,
        pincode: str = "",
    ) -> PriceQuote:
        """Fetch current stock, inventory quantity, and price for a pinned Amul SKU."""
        effective_pin = pincode or "110001"
        sku = external_variant_id or external_product_id

        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0) as client:
            substore = await self.get_substore_for_pincode(effective_pin, client)
            await self.set_substore_preference(substore, client)

            tid = await self._ensure_session(client)
            tid_hdr = self.calculate_tid_header(tid)
            headers = {**DEFAULT_HEADERS, "tid": tid_hdr}

            # Query within protein category with v=6 first to trigger StoreHippo regional substore computation
            query = (
                "filters[0][field]=categories&filters[0][value][0]=protein&filters[0][operator]=in&filters[0][original]=1"
                f"&filters[1][field]=sku&filters[1][value]={sku}&filters[1][operator]=equal&v=6"
            )
            url_api = f"{SHOP_URL}/api/1/entity/ms.products?{query}"
            resp = await client.get(url_api, headers=headers)
            if resp.status_code in (401, 403):
                logger.warning("Amul quote session expired (HTTP 401/403), re-establishing...", status=resp.status_code)
                self.invalidate_session()
                tid = await self._ensure_session(client)
                headers = {**DEFAULT_HEADERS, "tid": self.calculate_tid_header(tid)}
                resp = await client.get(url_api, headers=headers)

            if resp.status_code != 200:
                raise ExtractionError(f"HTTP {resp.status_code} fetching Amul SKU {sku}")

            data = resp.json()
            items = data.get("data", [])
            # If not found in protein category, fallback to SKU query with v=6
            if not items:
                fallback_query = f"filters[0][field]=sku&filters[0][value]={sku}&filters[0][operator]=equal&v=6"
                resp = await client.get(f"{SHOP_URL}/api/1/entity/ms.products?{fallback_query}", headers=headers)
                if resp.status_code == 200:
                    items = resp.json().get("data", [])

            if not items:
                raise ExtractionError(f"Amul SKU {sku} not found for substore {substore}")

            item = items[0]
            is_avail, eff_qty = self.calculate_effective_inventory(item)
            price_paise = parse_inr_to_paise(str(item.get("price", "0")))
            mrp_paise = parse_inr_to_paise(str(item.get("compare_price", "0")))

            return PriceQuote(
                external_product_id=external_product_id,
                external_variant_id=external_variant_id,
                price_paise=price_paise,
                mrp_paise=mrp_paise,
                currency="INR",
                available=is_avail,
                inventory_quantity=eff_qty,
                verified_pincode=effective_pin,
                extraction_method="amul_storehippo_api",
                raw_variant_title=item.get("name", "Standard"),
            )
