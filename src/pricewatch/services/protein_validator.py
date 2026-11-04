"""Protein percentage verification, quality filtering, and URL validation for whey supplements."""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional, Tuple

from pricewatch.logging_setup import get_logger
from pricewatch.services.flashtext_matcher import flashtext_matcher

logger = get_logger("protein_validator")

# Known low-grade / budget whey with < 65% protein, amino spiking concerns, or carb fillers
EXCLUDED_KEYWORDS = [
    "nakpro impact",
    "impact whey",         # Nakpro Impact or low-protein impact blends
    "mass gainer",
    "weight gainer",
    "super gainer",
    "serious mass",
    "carb gainer",
    "carbo",
    "vital whey",          # Nutrabay Vital Whey has ~60% protein (beginner budget blend)
    "pea protein",
    "soy protein",
    "yeast protein",
    "plant protein",
    "diet whey",
]

# Unflavoured detection keywords
UNFLAVOURED_KEYWORDS = [
    "unflavoured",
    "unflavored",
    "raw unflavoured",
    "raw whey",
    "natural unflavoured",
    "plain",
    "neutral",
    "raw",
]


def is_unflavoured_whey(title: str, variant: str = "") -> bool:
    """Returns True if the title or variant specifies raw/unflavoured whey via FlashText."""
    combined = f"{title} {variant}"
    return flashtext_matcher.is_unflavoured(combined)


def estimate_protein_percentage(title: str, variant: str = "") -> float:
    """
    Estimates protein percentage by weight from product title and variant.
    Returns estimated percentage (e.g., 80.0 for 80% WPC, 90.0 for Isolate).
    """
    combined = f"{title} {variant}".lower()

    # 1. Check for explicit percentage in title like 80%, 90%, 75%
    pct_match = re.search(r"\b(5\d|6\d|7\d|8\d|9\d)\s*%", combined)
    if pct_match:
        return float(pct_match.group(1))

    # 2. Check for "X g protein per Y g scoop" or "Xg / Yg"
    ratio_match = re.search(r"(\d+(?:\.\d+)?)\s*g\s*(?:protein)?\s*(?:per|\/|in)\s*(\d+(?:\.\d+)?)\s*g", combined)
    if ratio_match:
        try:
            prot = float(ratio_match.group(1))
            scoop = float(ratio_match.group(2))
            if 0 < scoop <= 60 and 0 < prot <= scoop:
                return (prot / scoop) * 100.0
        except (ValueError, ZeroDivisionError):
            pass

    # 3. Specific brand/line benchmarks
    if "nakpro impact" in combined:
        return 50.0  # ~50-52% protein, cheap budget blend
    if "vital whey" in combined:
        return 60.0  # ~60% protein

    if "isolate" in combined:
        return 90.0 if is_unflavoured_whey(title, variant) else 86.0
    if "hydrolyzed" in combined or "hydrolysate" in combined:
        return 88.0
    if "concentrate 80%" in combined or "wpc 80" in combined:
        return 80.0
    if "raw whey" in combined:
        return 80.0
    if "biozyme" in combined:
        return 75.8  # 25g per 33g scoop
    if "gold standard" in combined:
        return 78.9  # 24g per 30.4g scoop
    if "perform" in combined and "nakpro" in combined:
        return 72.7  # 24g per 33g scoop
    if "gold" in combined and "nakpro" in combined:
        return 77.2  # 25.5g per 33g scoop
    if "amul" in combined and "whey" in combined:
        return 80.0  # 25.6g per 32g sachet
    if "avvatar" in combined and "whey" in combined:
        return 77.1  # 27g per 35g scoop
    if "atom" in combined and "as-it-is" in combined:
        return 75.0  # 27g per 36g scoop

    # Generic whey concentrate default estimate
    if "concentrate" in combined or "whey" in combined:
        return 75.0

    return 70.0


def is_quality_whey(
    title: str,
    variant: str = "",
    min_protein_pct: float = 65.0,
) -> Tuple[bool, str, float]:
    """
    Validates whether a product meets quality standards via FlashText + ratio verification:
    - Must be whey protein (not mass gainer, plant, pea, etc.)
    - Excludes cheap quality whey like Nakpro Impact
    - Protein content must be >= 65% by weight.
    """
    combined = f"{title} {variant}"
    # 1. High-speed FlashText check
    is_ok, reason, est_pct = flashtext_matcher.check_quality_whey(combined, min_protein_pct=min_protein_pct)
    if not is_ok:
        return False, reason, est_pct

    # 2. Detailed percentage estimation if present in title
    detailed_pct = estimate_protein_percentage(title, variant)
    if detailed_pct < min_protein_pct:
        return False, f"Protein content ({detailed_pct:.1f}%) is below {min_protein_pct}% threshold", detailed_pct

    return True, "Quality standard passed", max(est_pct, detailed_pct)


def is_valid_product_url(url: str) -> bool:
    """
    Verifies that a URL actually leads directly to a specific product page,
    not a generic search query or broken stub.
    """
    if not url or not isinstance(url, str):
        return False

    url_clean = url.strip()
    url_low = url_clean.lower()

    # Must start with http:// or https://
    if not (url_low.startswith("http://") or url_low.startswith("https://")):
        return False

    # Must NOT be a search results page or generic category listing
    bad_patterns = [
        "/search?",
        "/search/",
        "?q=",
        "?txtq=",
        "/s?k=",
        "/browse/protein",
        "/collections/all",
        "flipkart.com/search",
        "amazon.in/s?",
        "nutrabay.com/search",
        "healthkart.com/search",
    ]
    if any(p in url_low for p in bad_patterns):
        return False

    # Domain-specific genuine product patterns
    if "amazon.in" in url_low:
        return bool(re.search(r"/dp/[A-Z0-9]{10}", url_clean, re.IGNORECASE))

    if "flipkart.com" in url_low:
        return "/p/itm" in url_low

    if "shop.amul.com" in url_low:
        return "/product/" in url_low

    if "nutrabay.com" in url_low:
        parts = url_low.split("/product/")
        return len(parts) > 1 and len(parts[-1].strip("/")) > 2

    if "healthkart.com" in url_low or "muscleblaze.com" in url_low:
        return "/sv/" in url_low or "/sp/" in url_low

    if "hyugalife.com" in url_low:
        parts = url_low.split("/product/")
        return len(parts) > 1 and len(parts[-1].strip("/")) > 2

    if "nakpro.com" in url_low or "asitisnutrition.com" in url_low:
        parts = url_low.split("/products/")
        return len(parts) > 1 and len(parts[-1].strip("/")) > 2

    # General fallback: must have a path with at least some slug
    parsed = urllib.parse.urlparse(url_clean)
    return len(parsed.path.strip("/")) > 3
