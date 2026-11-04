"""Ultra-fast keyword and entity extractor using FlashText (Trie-based O(N) scanner).

Specialized for Indian fitness supplements with primary focus on Unflavoured / Raw Whey:
- Instant unflavoured vs flavoured detection
- Brand subline and purity classification
- High-protein (>=65%) vs cheap/filler whey (e.g. Nakpro Impact, Mass Gainers)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from flashtext import KeywordProcessor

from pricewatch.logging_setup import get_logger

logger = get_logger("flashtext_matcher")


class WheyFlashTextMatcher:
    """Trie-based supplement entity extractor running 100x faster than regex."""

    def __init__(self):
        # 1. Unflavoured / Raw Whey Processor
        self.unflavoured_processor = KeywordProcessor(case_sensitive=False)
        self.unflavoured_processor.add_keywords_from_dict({
            "UNFLAVOURED": [
                "unflavoured",
                "unflavored",
                "raw unflavoured",
                "raw whey",
                "natural unflavoured",
                "plain",
                "neutral",
                "raw",
                "unflavoured raw",
                "100% unflavoured",
                "raw concentrate",
                "raw isolate",
            ]
        })

        # 2. Sweet / Added Flavours Processor
        self.flavour_processor = KeywordProcessor(case_sensitive=False)
        self.flavour_processor.add_keywords_from_dict({
            "CHOCOLATE": ["chocolate", "choco", "rich chocolate", "double rich chocolate", "dark chocolate", "fudge", "belgian chocolate", "molten chocolate cake"],
            "MALAI_KULFI": ["malai kulfi", "kulfi", "kesar kulfi"],
            "VANILLA": ["vanilla", "french vanilla", "creamy vanilla"],
            "MANGO": ["mango", "alphonso mango"],
            "COFFEE": ["coffee", "cafe mocha", "mocha", "cappuccino", "latte", "cold coffee"],
            "COOKIES_CREAM": ["cookies and cream", "cookies & cream", "cookies cream", "cookie"],
            "BERRY": ["strawberry", "berry", "blue berry", "blueberry"],
            "NUTTY": ["kesar pista", "pista", "pistachio", "hazelnut", "peanut", "choco peanut"],
            "CARAMEL": ["salted caramel", "caramel"],
        })

        # 3. Excluded Low-Grade / Non-Whey / Mass Gainer Processor
        self.exclusion_processor = KeywordProcessor(case_sensitive=False)
        self.exclusion_processor.add_keywords_from_dict({
            "NAKPRO_IMPACT": ["nakpro impact", "impact whey"],
            "MASS_GAINER": [
                "mass gainer", "weight gainer", "super gainer", "serious mass",
                "high carb", "carb gainer", "carbo", "mega mass", "xxl gainer",
            ],
            "LOW_PROTEIN_BLEND": [
                "vital whey", "beginner whey", "diet whey",
            ],
            "PLANT_OR_FILLERS": [
                "pea protein", "soy protein", "yeast protein", "plant blend",
            ],
        })

        # 4. Whey Form & High-Protein Indicator Processor
        self.form_processor = KeywordProcessor(case_sensitive=False)
        self.form_processor.add_keywords_from_dict({
            "ISOLATE_90": [
                "isolate", "100% isolate", "iso whey", "whey isolate",
                "platinum isolate", "atom iso",
            ],
            "HYDROLYZED_88": ["hydrolyzed", "hydrolysate", "hydro whey"],
            "CONCENTRATE_80": [
                "concentrate 80%", "wpc 80", "80% concentrate", "80% whey",
                "raw whey 80%", "biozyme", "gold standard",
            ],
        })

    def is_unflavoured(self, text: str) -> bool:
        """Instantly check if product is raw/unflavoured whey."""
        if not text:
            return False
        matches = self.unflavoured_processor.extract_keywords(text)
        return len(matches) > 0

    def extract_flavours(self, text: str) -> List[str]:
        """Extract sweet flavours present in product title."""
        if not text:
            return []
        return self.flavour_processor.extract_keywords(text)

    def check_quality_whey(self, text: str, min_protein_pct: float = 65.0) -> Tuple[bool, str, float]:
        """
        Validates quality using FlashText:
        - Drops mass gainers and cheap Nakpro Impact
        - Ensures product is pure whey with >= 65% protein
        """
        if not text:
            return False, "Empty product title", 0.0

        # Check exclusions
        exclusions = self.exclusion_processor.extract_keywords(text)
        if exclusions:
            tag = exclusions[0]
            if tag == "NAKPRO_IMPACT":
                return False, "Excluded cheap low-grade whey (Nakpro Impact ~50% protein)", 50.0
            if tag == "MASS_GAINER":
                return False, "Excluded Mass/Weight Gainer (<30% protein)", 25.0
            if tag == "LOW_PROTEIN_BLEND":
                return False, "Excluded beginner/low-protein whey blend (<65% protein)", 60.0
            if tag == "PLANT_OR_FILLERS":
                return False, "Excluded non-dairy / plant filler blend", 0.0

        low = text.lower()
        if not any(k in low for k in ("whey", "isolate", "wpc", "wpi")):
            return False, "Not a whey protein product", 0.0

        # Estimate protein percentage via forms
        forms = self.form_processor.extract_keywords(text)
        is_unflav = self.is_unflavoured(text)

        if "ISOLATE_90" in forms:
            est_pct = 90.0 if is_unflav else 86.0
        elif "HYDROLYZED_88" in forms:
            est_pct = 88.0
        elif "CONCENTRATE_80" in forms:
            est_pct = 80.0 if is_unflav else 76.0
        elif is_unflav:
            est_pct = 80.0  # Raw unflavoured whey standard is 80% WPC
        else:
            est_pct = 72.0

        if est_pct < min_protein_pct:
            return False, f"Protein content ({est_pct:.0f}%) below {min_protein_pct}%", est_pct

        return True, "Quality whey standard passed", est_pct


# Global singleton instance
flashtext_matcher = WheyFlashTextMatcher()
