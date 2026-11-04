"""Schema.org & JSON-LD Nutrition Facts Extractor using extruct.

Extracts structured metadata embedded by supplement brand stores:
- NutritionInformation (proteinContent, servingSize)
- Clean ground-truth protein % by weight
- Canonical product URLs directly from schema
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import extruct

from pricewatch.logging_setup import get_logger

logger = get_logger("nutrition_schema_extractor")


@dataclass
class SchemaNutritionInfo:
    product_name: str
    brand: Optional[str] = None
    canonical_url: Optional[str] = None
    serving_size_g: Optional[float] = None
    protein_content_g: Optional[float] = None
    protein_percentage: Optional[float] = None
    in_stock: Optional[bool] = None
    price: Optional[float] = None


def _parse_grams(val: Any) -> Optional[float]:
    """Parse integer or float grams from string or number."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams)?\b", s)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    return None


class NutritionSchemaExtractor:
    """Extracts structured Schema.org NutritionInformation and Product data via extruct."""

    def extract_from_html(self, html_text: str, base_url: str = "") -> Optional[SchemaNutritionInfo]:
        """Extracts product and nutrition facts from HTML via JSON-LD and Microdata."""
        if not html_text:
            return None

        try:
            data = extruct.extract(
                html_text,
                base_url=base_url or None,
                syntaxes=["json-ld", "microdata"],
                uniform=True,
            )
        except Exception as exc:
            logger.debug("extruct extraction failed", error=str(exc))
            return None

        # Gather all product nodes across JSON-LD and Microdata
        product_nodes: List[Dict[str, Any]] = []
        for syntax_key in ("json-ld", "microdata"):
            for item in data.get(syntax_key, []):
                t = str(item.get("@type", "")).lower()
                if "product" in t:
                    product_nodes.append(item)
                # Sometimes nested in @graph
                graph = item.get("@graph", [])
                if isinstance(graph, list):
                    for g in graph:
                        if "product" in str(g.get("@type", "")).lower():
                            product_nodes.append(g)

        if not product_nodes:
            return None

        # Take first valid product node
        prod = product_nodes[0]
        name = prod.get("name") or ""
        brand_info = prod.get("brand")
        brand = brand_info.get("name") if isinstance(brand_info, dict) else (str(brand_info) if brand_info else None)
        canon_url = prod.get("url") or prod.get("@id")

        # Extract nutrition information if present
        nutrition = prod.get("nutrition") or {}
        serving_g = _parse_grams(nutrition.get("servingSize"))
        protein_g = _parse_grams(nutrition.get("proteinContent"))

        prot_pct = None
        if serving_g and protein_g and 0 < serving_g <= 100 and 0 < protein_g <= serving_g:
            prot_pct = round((protein_g / serving_g) * 100.0, 1)

        # Offers / availability
        in_stock = None
        price = None
        offers = prod.get("offers")
        if isinstance(offers, dict):
            avail = str(offers.get("availability", "")).lower()
            if "instock" in avail:
                in_stock = True
            elif "outofstock" in avail:
                in_stock = False
            raw_p = offers.get("price")
            try:
                price = float(raw_p) if raw_p is not None else None
            except (ValueError, TypeError):
                pass
        elif isinstance(offers, list) and offers:
            o0 = offers[0]
            avail = str(o0.get("availability", "")).lower()
            if "instock" in avail:
                in_stock = True
            elif "outofstock" in avail:
                in_stock = False

        return SchemaNutritionInfo(
            product_name=name,
            brand=brand,
            canonical_url=canon_url,
            serving_size_g=serving_g,
            protein_content_g=protein_g,
            protein_percentage=prot_pct,
            in_stock=in_stock,
            price=price,
        )


schema_extractor = NutritionSchemaExtractor()
