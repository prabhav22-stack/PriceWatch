"""Cross-store discovery and price comparison engine."""

import re
from typing import List, Optional
from urllib.parse import urlparse

from pricewatch.domain.models import CanonicalListing, ComparisonResult, StoreDeal
from pricewatch.logging_setup import get_logger
from pricewatch.providers.base import ProviderRegistry
from pricewatch.services.discovery_matcher import (
    clean_product_tokens,
    compute_match_score,
    extract_brand,
    extract_weight_in_grams,
)
from pricewatch.services.store_searchers import query_all_stores

logger = get_logger("discovery_service")


class DiscoveryService:
    """Orchestrates cross-store product discovery, stock checks, and deal ranking."""

    @staticmethod
    def construct_search_query(title: str, variant_title: str = "") -> str:
        """Construct a high-signal search query from title and variant specifications."""
        # 1. Strip store branding suffixes from title (e.g. "| Nutrabay", "- Amazon.in")
        clean_title = re.sub(
            r"\s*(?:\||-)\s*(?:Nutrabay|Amazon|HealthKart|Shopify|Amul|Flipkart)\b.*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        combined = f"{clean_title} {variant_title}".strip()
        weight_g = extract_weight_in_grams(combined)
        brand = extract_brand(combined)

        core_tokens = clean_product_tokens(combined).split()
        key_terms = []
        if brand and brand.title() not in key_terms:
            key_terms.append(brand.title())

        for token in core_tokens:
            tok_title = token.title()
            if token.lower() != (brand or "").lower() and tok_title not in key_terms:
                key_terms.append(tok_title)
            if len(key_terms) >= 4:
                break

        if weight_g:
            if weight_g >= 1000 and weight_g % 1000 == 0:
                key_terms.append(f"{weight_g // 1000}kg")
            else:
                key_terms.append(f"{weight_g}g")

        return " ".join(key_terms)

    async def compare_listing(self, listing: CanonicalListing) -> ComparisonResult:
        """Compare a tracked or inspected canonical listing across trusted stores."""
        target_weight = (
            extract_weight_in_grams(listing.variant_title or "")
            or extract_weight_in_grams(listing.product_title)
            or extract_weight_in_grams(listing.package_quantity or "")
        )

        query = self.construct_search_query(listing.product_title, listing.variant_title or "")
        logger.info("Executing cross-store discovery", listing_id=listing.id, query=query)

        external_deals = await query_all_stores(query, target_weight_g=target_weight)

        # Include current listing as reference store deal
        current_store_name = listing.provider_code.title()
        if listing.provider_code == "generic":
            parsed = urlparse(listing.canonical_url)
            current_store_name = (parsed.hostname or "Current Store").replace("www.", "").title()

        current_deal = StoreDeal(
            store_name=current_store_name,
            product_title=listing.product_title,
            variant_title=listing.variant_title or "",
            price_paise=listing.last_price_paise or 0,
            mrp_paise=listing.last_mrp_paise,
            available=listing.last_available if listing.last_available is not None else True,
            url=listing.canonical_url,
            match_score=1.0,
            spec_weight_g=target_weight,
            price_per_100g_paise=(
                int(round((listing.last_price_paise or 0) * 100.0 / target_weight))
                if target_weight and listing.last_price_paise
                else None
            ),
        )

        all_candidates: List[StoreDeal] = [current_deal]
        # Deduplicate external deals: keep best in-stock, highest match per store
        seen_stores = {current_store_name.lower()}
        for deal in sorted(
            external_deals,
            key=lambda d: (1 if d.available else 0, d.match_score, -d.price_paise if d.price_paise > 0 else -999999999),
            reverse=True,
        ):
            s_name = deal.store_name.lower()
            if s_name not in seen_stores:
                seen_stores.add(s_name)
                all_candidates.append(deal)

        # Rank deals: In-stock first, then price ascending
        ranked = sorted(
            all_candidates,
            key=lambda d: (0 if d.available else 1, d.price_paise if d.price_paise > 0 else 999999999)
        )

        # Determine best deal and calculate savings
        in_stock_deals = [d for d in ranked if d.available and d.price_paise > 0]
        best_deal: Optional[StoreDeal] = None
        ref_price = listing.last_price_paise or 0

        final_deals: List[StoreDeal] = []
        for i, deal in enumerate(ranked):
            is_best = (in_stock_deals and deal == in_stock_deals[0])
            savings = max(0, ref_price - deal.price_paise) if ref_price > deal.price_paise else None

            updated_deal = deal.model_copy(update={
                "is_best_deal": is_best,
                "savings_paise": savings,
            })
            if is_best:
                best_deal = updated_deal
            final_deals.append(updated_deal)

        return ComparisonResult(
            query_title=listing.product_title,
            target_weight_g=target_weight,
            reference_price_paise=ref_price,
            reference_store=current_store_name,
            best_deal=best_deal,
            deals=final_deals,
            stores_checked=len(seen_stores),
        )

    async def compare_query(self, query_or_url: str) -> ComparisonResult:
        """Compare products given an arbitrary search query or direct product URL."""
        # 1. If input is a URL, resolve listing first
        parsed = urlparse(query_or_url.strip())
        if parsed.scheme in ("http", "https") and bool(parsed.hostname):
            provider = ProviderRegistry.get_provider_for_url(query_or_url)
            res = await provider.resolve_url(query_or_url)
            # Pick pinned variant or first variant
            first_v = res.variants[0] if res.variants else None
            price = first_v.price_paise if first_v else 0
            mrp = first_v.mrp_paise if first_v else None
            avail = first_v.available if first_v else True
            v_title = first_v.variant_title if first_v else ""

            pseudo_listing = CanonicalListing(
                provider_code=provider.provider_code,
                external_product_id=res.external_product_id,
                canonical_url=query_or_url,
                product_title=res.product_title,
                variant_title=v_title,
                last_price_paise=price,
                last_mrp_paise=mrp,
                last_available=avail,
            )
            return await self.compare_listing(pseudo_listing)

        # 2. Text query mode
        query = query_or_url.strip()
        target_weight = extract_weight_in_grams(query)
        logger.info("Executing text query cross-store discovery", query=query)

        external_deals = await query_all_stores(query, target_weight_g=target_weight)

        # Deduplicate best in-stock, highest match deal per store
        seen_stores = set()
        deduped: List[StoreDeal] = []
        for deal in sorted(
            external_deals,
            key=lambda d: (1 if d.available else 0, d.match_score, -d.price_paise if d.price_paise > 0 else -999999999),
            reverse=True,
        ):
            s_name = deal.store_name.lower()
            if s_name not in seen_stores:
                seen_stores.add(s_name)
                deduped.append(deal)

        # Rank deals: In-stock first, lowest price first
        ranked = sorted(
            deduped,
            key=lambda d: (0 if d.available else 1, d.price_paise if d.price_paise > 0 else 999999999)
        )

        in_stock = [d for d in ranked if d.available and d.price_paise > 0]
        best_deal = None
        final_deals: List[StoreDeal] = []

        for d in ranked:
            is_best = (in_stock and d == in_stock[0])
            updated = d.model_copy(update={"is_best_deal": is_best})
            if is_best:
                best_deal = updated
            final_deals.append(updated)

        return ComparisonResult(
            query_title=query,
            target_weight_g=target_weight,
            reference_price_paise=None,
            reference_store=None,
            best_deal=best_deal,
            deals=final_deals,
            stores_checked=len(seen_stores),
        )

    async def find_in_stock_alternative(self, listing: CanonicalListing) -> Optional[StoreDeal]:
        """Check alternative trusted stores for an identical product that is currently in stock."""
        comp_res = await self.compare_listing(listing)
        curr_store = listing.provider_code.lower()

        # Find first in-stock deal on an alternative store
        for deal in comp_res.deals:
            if deal.available and deal.price_paise > 0 and deal.url:
                deal_store = deal.store_name.lower().replace(" direct", "")
                if deal_store != curr_store and "amul" not in deal_store:
                    return deal
        return None

