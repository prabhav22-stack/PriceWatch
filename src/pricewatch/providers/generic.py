"""Tier 2/3 Generic provider extracting JSON-LD, OpenGraph, and scoped HTML."""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.exceptions import ExtractionError
from pricewatch.domain.models import PriceQuote, ResolutionResult, VariantOption
from pricewatch.providers.base import BaseProvider, ProviderRegistry
from pricewatch.providers.http_client import http_client
from pricewatch.validation.normalizer import parse_inr_to_paise


_STRIP_SELECTORS = [
    "aside",
    "footer",
    "nav",
    '[class*="recommend"]',
    '[class*="similar"]',
    '[class*="upsell"]',
    '[class*="related"]',
    '[id*="sponsored"]',
    "del",
    "s",
]

_PRICE_CLASS_PATTERNS = [
    '[class*="priceToPay"]',
    '[class*="current-price"]',
    '[class*="final-price"]',
    '[class*="special-price"]',
    '[class*="sale-price"]',
    '[itemprop="price"]',
    '[data-price]',
    ".price",
]


class GenericProvider(BaseProvider):
    """Fallback provider for stores without a dedicated API adapter."""

    provider_code = "generic"
    tier = ProviderTier.STRUCTURED_DATA

    @classmethod
    def can_handle(cls, url: str) -> bool:
        # Fallback provider handles any valid HTTP/HTTPS URL
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)

    @staticmethod
    def _generate_product_id(url: str) -> str:
        parsed = urlparse(url)
        clean = f"{parsed.netloc}{parsed.path}"
        return hashlib.md5(clean.encode()).hexdigest()[:16]

    def _extract_json_ld(self, parser: LexborHTMLParser) -> Optional[Dict[str, Any]]:
        """Extract Schema.org/Product structured data."""
        for script in parser.css('script[type="application/ld+json"]'):
            text = script.text()
            if not text:
                continue
            try:
                data = json.loads(text.strip())
            except Exception:
                continue

            # Support single object, @graph array, or list of objects
            items = data if isinstance(data, list) else data.get("@graph", [data])
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")
                if item_type in ("Product", "ProductGroup"):
                    return item
        return None

    def _extract_opengraph(self, parser: LexborHTMLParser) -> Tuple[Optional[str], Optional[int]]:
        """Extract OpenGraph metadata."""
        title_tag = parser.css_first('meta[property="og:title"]')
        title = title_tag.attributes.get("content") if title_tag else None

        price_tag = parser.css_first('meta[property="product:price:amount"]')
        price = parse_inr_to_paise(price_tag.attributes.get("content")) if price_tag else None

        return title, price

    def _extract_dom_fallback(self, parser: LexborHTMLParser) -> Tuple[Optional[str], Optional[int]]:
        """Extract price and title from DOM with noise suppression."""
        title_node = parser.css_first("h1") or parser.css_first("title")
        title = title_node.text(strip=True) if title_node else "Tracked Product"

        # Search for price using candidate selectors
        for selector in _PRICE_CLASS_PATTERNS:
            node = parser.css_first(selector)
            if node:
                # Avoid contaminated parent nodes
                text = node.text(strip=True)
                paise = parse_inr_to_paise(text)
                if paise and paise > 0:
                    return title, paise

        return title, None

    async def _parse_page(self, url: str) -> Tuple[str, Optional[int], Optional[int], bool, str]:
        """Parse HTML page returning (title, price_paise, mrp_paise, available, method)."""
        resp = await http_client.get(url)
        if resp.status_code != 200:
            raise ExtractionError(f"HTTP {resp.status_code} when fetching {url}")

        html = resp.text
        parser = LexborHTMLParser(html)

        # 1. Try JSON-LD
        product_ld = self._extract_json_ld(parser)
        if product_ld:
            title = product_ld.get("name") or "Tracked Product"
            offers = product_ld.get("offers", {})
            if isinstance(offers, list) and offers:
                offers = offers[0]

            raw_price = offers.get("price")
            price_paise = parse_inr_to_paise(raw_price)
            availability_str = str(offers.get("availability", "")).lower()
            available = "outofstock" not in availability_str

            if price_paise:
                return title, price_paise, None, available, "json_ld"

        # 2. Try OpenGraph
        og_title, og_price = self._extract_opengraph(parser)
        if og_price:
            return og_title or "Tracked Product", og_price, None, True, "opengraph"

        # 3. Strip noise nodes and try DOM selectors
        for tag in _STRIP_SELECTORS:
            for node in parser.css(tag):
                node.decompose()

        dom_title, dom_price = self._extract_dom_fallback(parser)
        if dom_price:
            return dom_title, dom_price, None, True, "scoped_dom"

        raise ExtractionError(f"Could not extract price from {url} using JSON-LD, OpenGraph, or DOM")

    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        title, price_paise, mrp_paise, available, method = await self._parse_page(url)
        product_id = self._generate_product_id(url)

        variant = VariantOption(
            external_variant_id="default",
            variant_title="Standard",
            canonical_url=url,
            price_paise=price_paise,
            mrp_paise=mrp_paise,
            available=available,
        )

        domain = urlparse(url).hostname or "unknown"
        provider_code = f"generic:{domain.replace('www.', '')}"

        return ResolutionResult(
            provider_code=provider_code,
            provider_tier=self.tier,
            external_product_id=product_id,
            product_title=title,
            requires_pincode=False,
            variants=[variant],
            pinned_variant_id="default",
        )

    async def fetch_quote(
        self,
        canonical_url: str,
        external_product_id: str,
        external_variant_id: str,
        pincode: str = "",
    ) -> PriceQuote:
        title, price_paise, mrp_paise, available, method = await self._parse_page(canonical_url)

        return PriceQuote(
            external_product_id=external_product_id,
            external_variant_id=external_variant_id,
            price_paise=price_paise,
            mrp_paise=mrp_paise,
            currency="INR",
            available=available,
            verified_pincode="",
            extraction_method=method,
            raw_variant_title="Standard",
        )


# Set GenericProvider as fallback in registry
ProviderRegistry.set_fallback(GenericProvider)
