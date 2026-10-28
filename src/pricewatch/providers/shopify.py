"""Universal Shopify provider for D2C brands (Nakpro, MuscleBlaze, etc.)."""

import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.exceptions import (
    ExtractionError,
    ProductNotFoundError,
    VariantAmbiguousError,
    VariantNotFoundError,
)
from pricewatch.domain.models import PriceQuote, ResolutionResult, VariantOption
from pricewatch.providers.base import BaseProvider, ProviderRegistry
from pricewatch.providers.http_client import http_client
from pricewatch.validation.normalizer import parse_inr_to_paise


_KNOWN_SHOPIFY_DOMAINS = {
    "nakpro.com",
    "kapiva.in",
    "bepure.co.in",
    "myprotein.co.in",
}

_PRODUCT_PATH_REGEX = re.compile(r"/products/([a-zA-Z0-9_-]+)")


@ProviderRegistry.register
class ShopifyProvider(BaseProvider):
    """Tier 1: Store JSON API provider querying /products/{handle}.js."""

    provider_code = "shopify"
    tier = ProviderTier.API_OR_JSON

    @classmethod
    def can_handle(cls, url: str) -> bool:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower().replace("www.", "")
        if domain in _KNOWN_SHOPIFY_DOMAINS:
            return True
        # If path looks like Shopify /products/<handle>
        return bool(_PRODUCT_PATH_REGEX.search(parsed.path))

    @staticmethod
    def _extract_handle_and_domain(url: str) -> Tuple[str, str, Optional[str]]:
        """Extract (domain, handle, variant_param) from Shopify URL."""
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        match = _PRODUCT_PATH_REGEX.search(parsed.path)
        if not match:
            raise ExtractionError(f"Cannot extract product handle from URL: {url}")
        handle = match.group(1)

        query = parse_qs(parsed.query)
        variant_id = query.get("variant", [None])[0]
        return domain, handle, variant_id

    async def _fetch_product_json(self, domain: str, handle: str) -> dict:
        """Fetch and parse /products/{handle}.js endpoint."""
        url = f"https://{domain}/products/{handle}.js"
        try:
            resp = await http_client.get(url)
        except Exception as exc:
            raise ExtractionError(f"Failed to fetch Shopify JSON from {url}: {exc}") from exc

        if resp.status_code == 404:
            raise ProductNotFoundError(f"Product '{handle}' not found on {domain} (404)")
        if resp.status_code != 200:
            raise ExtractionError(f"Shopify endpoint {url} returned HTTP {resp.status_code}")

        try:
            data = resp.json()
            return data
        except Exception as exc:
            raise ExtractionError(f"Failed to decode Shopify JSON from {url}: {exc}") from exc

    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        domain, handle, requested_variant_id = self._extract_handle_and_domain(url)
        data = await self._fetch_product_json(domain, handle)

        product_title = data.get("title", handle)
        raw_variants = data.get("variants", [])

        if not raw_variants:
            raise ExtractionError(f"No variants found for product {handle} on {domain}")

        variants: List[VariantOption] = []
        for v in raw_variants:
            v_id = str(v.get("id"))
            v_title = v.get("title", "Default Title")
            # In Shopify .js, price is in cents/paise (e.g. 149900 = Rs. 1499.00)
            price_paise = v.get("price")
            compare_paise = v.get("compare_at_price")
            available = bool(v.get("available", False))

            v_url = f"https://{domain}/products/{handle}?variant={v_id}"
            variants.append(
                VariantOption(
                    external_variant_id=v_id,
                    variant_title=v_title,
                    canonical_url=v_url,
                    price_paise=price_paise,
                    mrp_paise=compare_paise,
                    available=available,
                )
            )

        pinned_id: Optional[str] = None
        if requested_variant_id:
            # User provided explicit ?variant= in URL
            found = next((v for v in variants if v.external_variant_id == str(requested_variant_id)), None)
            if not found:
                raise VariantNotFoundError(
                    f"Requested variant '{requested_variant_id}' not found for product '{handle}'"
                )
            pinned_id = str(requested_variant_id)
        else:
            if len(variants) == 1:
                pinned_id = variants[0].external_variant_id
            else:
                # Multi-variant product without pinned variant; raise so Telegram can show inline options
                raise VariantAmbiguousError(
                    f"Product has {len(variants)} variants. Please select which variant to track.",
                    variants=variants,
                )

        provider_code = f"shopify:{domain.replace('www.', '')}"
        return ResolutionResult(
            provider_code=provider_code,
            provider_tier=self.tier,
            external_product_id=handle,
            product_title=product_title,
            requires_pincode=False,
            variants=variants,
            pinned_variant_id=pinned_id,
        )

    async def fetch_quote(
        self,
        canonical_url: str,
        external_product_id: str,
        external_variant_id: str,
        pincode: str = "",
    ) -> PriceQuote:
        domain, handle, _ = self._extract_handle_and_domain(canonical_url)
        data = await self._fetch_product_json(domain, handle)

        raw_variants = data.get("variants", [])
        target = next((v for v in raw_variants if str(v.get("id")) == str(external_variant_id)), None)
        if not target:
            raise VariantNotFoundError(
                f"Variant '{external_variant_id}' not found in updated listing for {handle}"
            )

        price_paise = target.get("price")
        mrp_paise = target.get("compare_at_price")
        available = bool(target.get("available", False))
        variant_title = target.get("title")

        return PriceQuote(
            external_product_id=handle,
            external_variant_id=str(external_variant_id),
            price_paise=price_paise,
            mrp_paise=mrp_paise,
            currency="INR",
            available=available,
            verified_pincode="",
            extraction_method="shopify_js",
            seller_name=data.get("vendor", domain),
            raw_variant_title=variant_title,
        )
