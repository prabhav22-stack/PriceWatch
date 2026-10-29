"""Dedicated Nutrabay provider using Next.js __NEXT_DATA__ structured extraction."""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from selectolax.lexbor import LexborHTMLParser

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


@ProviderRegistry.register
class NutrabayProvider(BaseProvider):
    """Tier 1: Next.js embedded JSON provider for Nutrabay products."""

    provider_code = "nutrabay"
    tier = ProviderTier.API_OR_JSON

    @classmethod
    def can_handle(cls, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return "nutrabay.com" in hostname

    async def _fetch_next_data(self, url: str) -> tuple[dict, LexborHTMLParser]:
        """Fetch Nutrabay page and extract __NEXT_DATA__ JSON payload."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            resp = await http_client.get(url, headers=headers)
        except Exception as exc:
            raise ExtractionError(f"Failed to fetch Nutrabay product page: {exc}") from exc

        if resp.status_code == 404:
            raise ProductNotFoundError(f"Nutrabay product not found: {url}")
        if resp.status_code != 200:
            raise ExtractionError(f"Nutrabay returned HTTP {resp.status_code}")

        parser = LexborHTMLParser(resp.text)
        script_tag = parser.css_first('script#__NEXT_DATA__')
        if not script_tag:
            raise ExtractionError(f"Missing __NEXT_DATA__ in Nutrabay page: {url}")

        try:
            data = json.loads(script_tag.text())
        except Exception as exc:
            raise ExtractionError(f"Failed to parse __NEXT_DATA__ JSON: {exc}") from exc

        return data, parser

    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        """Inspect Nutrabay URL and return available product variants."""
        data, parser = await self._fetch_next_data(url)
        props = data.get("props", {}).get("pageProps", {})
        initial_state = props.get("initialState", {})
        parent_product = initial_state.get("parentProduct", {})

        p_details = parent_product.get("getParentDetails", {}).get("data", {}).get("data", {})
        var_data = parent_product.get("getVariantDetails", {}).get("data", {}).get("data", {})

        # Extract title
        title = (
            var_data.get("parent_name")
            or (og_node := parser.css_first('meta[property="og:title"]')) and og_node.attributes.get("content")
            or (h1_node := parser.css_first("h1")) and h1_node.text(strip=True)
            or "Nutrabay Product"
        )
        # Clean title suffix if present
        title = re.sub(r"\s*\|\s*Nutrabay.*$", "", title, flags=re.IGNORECASE).strip()

        # Parse query params for pId and vId
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        url_pid = query.get("pId", [None])[0]
        url_vid = query.get("vId", [None])[0]

        # Extract parent product ID
        parent_id = (
            url_pid
            or props.get("pId")
            or p_details.get("parent_details", {}).get("parent_id")
            or var_data.get("parent_product_id")
            or str(hash(parsed.path))
        )
        parent_id = str(parent_id)

        # Collect variants
        variants_list = p_details.get("variants") or []
        variants: List[VariantOption] = []

        if variants_list:
            for v in variants_list:
                vid = str(v.get("variant_id") or v.get("sku") or "")
                if not vid:
                    continue

                # Swatch / Variant display name
                swatches = v.get("selected_swatch_display_names") or []
                v_title = ""
                if isinstance(swatches, list) and swatches:
                    v_title = ", ".join(str(val) for s in swatches for val in s.values())
                if not v_title:
                    v_title = v.get("name") or "Standard"

                sale_price = parse_inr_to_paise(str(v.get("sale_price") or 0))
                mrp = parse_inr_to_paise(str(v.get("mrp_price") or v.get("mrp") or 0))
                stock_status = bool(v.get("stock_status", False))
                stock_qty = v.get("stock_quantity")
                available = stock_status and (stock_qty is None or stock_qty > 0)
                variant_canonical = f"https://nutrabay.com{parsed.path}?pId={parent_id}&vId={vid}"

                # Parse updated_at and warehouse breakdown for stock intelligence
                raw_updated = v.get("updated_at") or var_data.get("updated_at")
                updated_at_dt = None
                if raw_updated and isinstance(raw_updated, str):
                    try:
                        clean = raw_updated.strip().replace(" ", "T")
                        updated_at_dt = datetime.fromisoformat(clean)
                        if updated_at_dt.tzinfo is None:
                            updated_at_dt = updated_at_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        updated_at_dt = None

                wh_meta = v.get("wh_meta") or var_data.get("wh_meta")
                warehouse_stock = None
                if isinstance(wh_meta, dict):
                    warehouse_stock = {str(k): int(val) for k, val in wh_meta.items() if isinstance(val, (int, float, str)) and str(val).isdigit()}

                variants.append(
                    VariantOption(
                        external_variant_id=vid,
                        variant_title=v_title,
                        canonical_url=variant_canonical,
                        price_paise=sale_price or 0,
                        mrp_paise=mrp or None,
                        available=available,
                        inventory_quantity=stock_qty,
                        last_in_stock_at=updated_at_dt,
                        warehouse_stock=warehouse_stock,
                    )
                )

        # If getParentDetails.variants was empty, check getVariantDetails
        if not variants and var_data:
            vid = str(var_data.get("variant_product_id") or var_data.get("variant_woo_id") or url_vid or "1")
            v_title = var_data.get("variant_swatch_name") or "Standard"
            sale_price = parse_inr_to_paise(str(var_data.get("sale_price") or 0))
            mrp = parse_inr_to_paise(str(var_data.get("regular_price") or var_data.get("mrp") or 0))
            stock_status = bool(var_data.get("stock_status", False))
            stock_qty = var_data.get("stock_quantity")
            available = stock_status and (stock_qty is None or stock_qty > 0)
            variant_canonical = f"https://nutrabay.com{parsed.path}?pId={parent_id}&vId={vid}"

            raw_updated = var_data.get("updated_at")
            updated_at_dt = None
            if raw_updated and isinstance(raw_updated, str):
                try:
                    clean = raw_updated.strip().replace(" ", "T")
                    updated_at_dt = datetime.fromisoformat(clean)
                    if updated_at_dt.tzinfo is None:
                        updated_at_dt = updated_at_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    updated_at_dt = None

            wh_meta = var_data.get("wh_meta")
            warehouse_stock = None
            if isinstance(wh_meta, dict):
                warehouse_stock = {str(k): int(val) for k, val in wh_meta.items() if isinstance(val, (int, float, str)) and str(val).isdigit()}

            variants.append(
                VariantOption(
                    external_variant_id=vid,
                    variant_title=v_title,
                    canonical_url=variant_canonical,
                    price_paise=sale_price or 0,
                    mrp_paise=mrp or None,
                    available=available,
                    inventory_quantity=stock_qty,
                    last_in_stock_at=updated_at_dt,
                    warehouse_stock=warehouse_stock,
                )
            )

        if not variants:
            raise ExtractionError(f"No purchasable variants found for Nutrabay product: {url}")

        # Check if a specific variant was targeted via URL
        pinned_id: Optional[str] = None
        if url_vid:
            matching = next((o for o in variants if o.external_variant_id == str(url_vid)), None)
            if matching:
                pinned_id = matching.external_variant_id

        # If only 1 option available, automatically pin it
        if len(variants) == 1:
            pinned_id = variants[0].external_variant_id

        # If multiple variants and no specific variant pinned, raise VariantAmbiguousError
        if len(variants) > 1 and not pinned_id:
            raise VariantAmbiguousError(
                f"Nutrabay product '{title}' has multiple variants.",
                variants=variants,
            )

        return ResolutionResult(
            provider_code=self.provider_code,
            provider_tier=self.tier,
            external_product_id=parent_id,
            product_title=title,
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
        """Fetch current price, MRP, and stock status for pinned Nutrabay listing."""
        data, parser = await self._fetch_next_data(canonical_url)
        props = data.get("props", {}).get("pageProps", {})
        initial_state = props.get("initialState", {})
        parent_product = initial_state.get("parentProduct", {})

        p_details = parent_product.get("getParentDetails", {}).get("data", {}).get("data", {})
        var_data = parent_product.get("getVariantDetails", {}).get("data", {}).get("data", {})
        variants = p_details.get("variants") or []

        matched_variant = None
        for v in variants:
            if str(v.get("variant_id") or "") == str(external_variant_id):
                matched_variant = v
                break

        if not matched_variant and var_data:
            if str(var_data.get("variant_product_id") or "") == str(external_variant_id):
                matched_variant = var_data

        if not matched_variant:
            # Fallback to var_data if available
            matched_variant = var_data or (variants[0] if variants else None)

        if not matched_variant:
            raise VariantNotFoundError(
                f"Variant {external_variant_id} not found on Nutrabay listing: {canonical_url}"
            )

        sale_price = parse_inr_to_paise(str(matched_variant.get("sale_price") or 0))
        mrp = parse_inr_to_paise(
            str(matched_variant.get("mrp_price") or matched_variant.get("mrp") or matched_variant.get("regular_price") or 0)
        )
        stock_status = bool(matched_variant.get("stock_status", False))
        stock_qty = matched_variant.get("stock_quantity")
        available = stock_status and (stock_qty is None or stock_qty > 0)

        # Variant display title
        swatches = matched_variant.get("selected_swatch_display_names") or []
        v_title = ""
        if isinstance(swatches, list) and swatches:
            v_title = ", ".join(str(val) for s in swatches for val in s.values())
        if not v_title:
            v_title = matched_variant.get("variant_swatch_name") or matched_variant.get("name") or "Standard"

        raw_updated = matched_variant.get("updated_at") or var_data.get("updated_at")
        updated_at_dt = None
        if raw_updated and isinstance(raw_updated, str):
            try:
                clean = raw_updated.strip().replace(" ", "T")
                updated_at_dt = datetime.fromisoformat(clean)
                if updated_at_dt.tzinfo is None:
                    updated_at_dt = updated_at_dt.replace(tzinfo=timezone.utc)
            except Exception:
                updated_at_dt = None

        wh_meta = matched_variant.get("wh_meta") or var_data.get("wh_meta")
        warehouse_stock = None
        if isinstance(wh_meta, dict):
            warehouse_stock = {str(k): int(val) for k, val in wh_meta.items() if isinstance(val, (int, float, str)) and str(val).isdigit()}

        return PriceQuote(
            external_product_id=external_product_id,
            external_variant_id=external_variant_id,
            price_paise=sale_price or 0,
            mrp_paise=mrp or None,
            available=available,
            inventory_quantity=stock_qty,
            raw_variant_title=v_title,
            seller_name="Nutrabay",
            extraction_method="nutrabay:next_data",
            last_in_stock_at=updated_at_dt,
            stock_updated_at=updated_at_dt,
            warehouse_stock=warehouse_stock,
        )
