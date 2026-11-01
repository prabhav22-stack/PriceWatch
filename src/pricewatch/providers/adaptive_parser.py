"""Adaptive and self-healing e-commerce parser powered by Scrapling.

Provides resilient element tracking, regex text discovery, and DOM similarity matching
when e-commerce websites (Amazon, Flipkart, Nutrabay, etc.) change their CSS class names.
"""

import re
from typing import Any, List, Optional, Tuple
from scrapling import Selector

from pricewatch.logging_setup import get_logger
from pricewatch.validation.normalizer import parse_inr_to_paise

logger = get_logger("adaptive_parser")

_OUT_OF_STOCK_PATTERNS = [
    re.compile(r"currently\s+unavailable", re.I),
    re.compile(r"out\s+of\s+stock", re.I),
    re.compile(r"sold\s+out", re.I),
    re.compile(r"temporarily\s+out\s+of\s+stock", re.I),
    re.compile(r"we\s+don't\s+know\s+when\s+or\s+if\s+this\s+item\s+will\s+be\s+back\s+in\s+stock", re.I),
]

_IN_STOCK_PATTERNS = [
    re.compile(r"in\s+stock", re.I),
    re.compile(r"add\s+to\s+cart", re.I),
    re.compile(r"buy\s+now", re.I),
    re.compile(r"order\s+now", re.I),
]

_PRICE_REGEX = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?)", re.I)


def _elem_to_str(elem: Any) -> str:
    if elem is None:
        return ""
    if isinstance(elem, str):
        return elem.strip()
    if hasattr(elem, "text") and elem.text:
        return str(elem.text).strip()
    return str(elem).strip()


class AdaptiveEcomParser:
    """Resilient e-commerce parser that dynamically recovers when classes change."""

    def __init__(self, html: str):
        self.raw_html = html
        self.selector = Selector(html)

    def extract_title(self, fallback_selectors: Optional[List[str]] = None) -> str:
        """Extract product title using meta tags, standard tags, or provided selectors."""
        # 1. Try provided selectors
        if fallback_selectors:
            for sel in fallback_selectors:
                match = self.selector.css(f"{sel}::text")
                if match:
                    title_text = " ".join([_elem_to_str(t) for t in match if _elem_to_str(t)])
                    if title_text:
                        return title_text

        # 2. Try OpenGraph / Twitter meta tags
        og_match = self.selector.css('meta[property="og:title"]::attr(content)')
        if og_match:
            text = _elem_to_str(og_match[0])
            if text:
                return text

        # 3. Try standard h1
        h1_match = self.selector.css("h1::text")
        if h1_match:
            t = " ".join([_elem_to_str(m) for m in h1_match if _elem_to_str(m)])
            if t:
                return t

        # 4. Fallback to <title>
        title_tag = self.selector.css("title::text")
        if title_tag:
            text = _elem_to_str(title_tag[0])
            if text:
                return text

        return ""

    def extract_price(self, preferred_selectors: Optional[List[str]] = None) -> Optional[int]:
        """
        Extract selling price in paise.
        First attempts preferred CSS selectors, then falls back to Scrapling's adaptive regex discovery.
        """
        # 1. Preferred selectors
        if preferred_selectors:
            for sel in preferred_selectors:
                elements = self.selector.css(f"{sel}::text")
                for elem in elements:
                    text = _elem_to_str(elem)
                    paise = parse_inr_to_paise(text)
                    if paise and paise > 0:
                        return paise

        # 2. Adaptive regex search on DOM text elements
        price_matches = self.selector.find_by_regex(_PRICE_REGEX)
        nodes = price_matches if isinstance(price_matches, list) else [price_matches]
        for node in nodes:
            if not node or not hasattr(node, "iterancestors"):
                continue
            # Check if this node is inside a del/strike (MRP)
            ancestors = [a.tag for a in node.iterancestors()]
            if any(t in ("del", "s", "strike") for t in ancestors):
                continue

            node_text = node.get_all_text() if hasattr(node, "get_all_text") else _elem_to_str(node)
            match = _PRICE_REGEX.search(node_text)
            if match:
                paise = parse_inr_to_paise(match.group(0))
                if paise and paise > 0:
                    return paise

        return None

    def extract_mrp(self, preferred_selectors: Optional[List[str]] = None) -> Optional[int]:
        """Extract MRP (original/strike-through price) in paise."""
        if preferred_selectors:
            for sel in preferred_selectors:
                elements = self.selector.css(f"{sel}::text")
                for elem in elements:
                    paise = parse_inr_to_paise(_elem_to_str(elem))
                    if paise and paise > 0:
                        return paise

        # Adaptive search for strike/del tags
        strike_elements = self.selector.css("del, s, strike, span[style*='line-through']")
        for elem in strike_elements:
            text = elem.get_all_text() if hasattr(elem, "get_all_text") else _elem_to_str(elem)
            match = _PRICE_REGEX.search(text)
            if match:
                paise = parse_inr_to_paise(match.group(0))
                if paise and paise > 0:
                    return paise

        return None

    def detect_availability(self, preferred_selectors: Optional[List[str]] = None) -> bool:
        """
        Detect whether the product is in stock.
        Checks for out-of-stock markers first, then in-stock confirmations.
        """
        full_text = self.selector.get_all_text()

        # 1. Out of stock signals
        for pattern in _OUT_OF_STOCK_PATTERNS:
            if pattern.search(full_text):
                return False

        # 2. In stock signals
        for pattern in _IN_STOCK_PATTERNS:
            if pattern.search(full_text):
                return True

        # Default to True if no explicit OOS found
        return True

    def extract_all(
        self,
        price_selectors: Optional[List[str]] = None,
        mrp_selectors: Optional[List[str]] = None,
        title_selectors: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[int], Optional[int], bool]:
        """Return (title, price_paise, mrp_paise, is_available)."""
        title = self.extract_title(title_selectors)
        price_paise = self.extract_price(price_selectors)
        mrp_paise = self.extract_mrp(mrp_selectors)
        is_available = self.detect_availability()

        return title, price_paise, mrp_paise, is_available
