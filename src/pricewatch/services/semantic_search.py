"""Semantic Fitness & Dietary Goal Search Engine.

Maps natural fitness queries, medical/dietary restrictions, and athletic goals
(e.g., lactose intolerance, severe bloating, clean cutting, budget student, stim-free)
to supplement attributes and ingredients without requiring heavy PyTorch downloads.
"""

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pricewatch.logging_setup import get_logger

logger = get_logger("services.semantic_search")


@dataclass
class FitnessIntent:
    category: str
    target_attributes: List[str]
    avoid_attributes: List[str]
    recommended_keywords: List[str]
    explanation: str


INTENT_KNOWLEDGE_BASE: Dict[str, FitnessIntent] = {
    "lactose_sensitive": FitnessIntent(
        category="whey_isolate",
        target_attributes=["isolate", "hydrolyzed", "plant", "digezyme", "enzymes", "unflavoured"],
        avoid_attributes=["concentrate", "casein", "skimmed milk"],
        recommended_keywords=["isolate", "hydrolyzed", "digezyme", "plant"],
        explanation="Recommended 100% Whey Isolate or Plant Protein with added digestive enzymes (DigeZyme) to prevent bloating and gas.",
    ),
    "cutting_fat_loss": FitnessIntent(
        category="whey_isolate",
        target_attributes=["isolate", "hydrolyzed", "zero carb", "zero sugar", "unflavoured"],
        avoid_attributes=["gainer", "maltodextrin", "added sugar"],
        recommended_keywords=["isolate", "unflavoured", "zero sugar"],
        explanation="Recommended high-purity Whey Isolate with minimal carbs and zero added sugar for lean fat loss.",
    ),
    "budget_value": FitnessIntent(
        category="whey_concentrate",
        target_attributes=["concentrate", "raw", "nakpro", "asitis", "amul", "80%"],
        avoid_attributes=["expensive", "hydrolyzed"],
        recommended_keywords=["concentrate", "raw", "nakpro", "asitis", "amul"],
        explanation="Recommended Raw Whey Concentrate 80% offering the highest protein-to-rupee ratio in India.",
    ),
    "lab_purity": FitnessIntent(
        category="certified",
        target_attributes=["trustified", "labdoor", "informed-choice", "unflavoured", "third-party"],
        avoid_attributes=["proprietary blend", "untested"],
        recommended_keywords=["trustified", "labdoor", "biozyme", "nakpro", "amul"],
        explanation="Filtered for third-party blind laboratory certified products tested for zero amino spiking and safe heavy metals.",
    ),
    "stim_free": FitnessIntent(
        category="pre_workout",
        target_attributes=["creatine", "citrulline", "caffeine-free", "stim-free", "monohydrate"],
        avoid_attributes=["caffeine", "beta-alanine", "stimulant"],
        recommended_keywords=["creatine", "caffeine free", "stim free"],
        explanation="Recommended pure Creatine Monohydrate or Stim-Free pre-workout with zero beta-alanine tingles or sleep disruption.",
    ),
}

INTENT_TRIGGERS: List[Tuple[str, List[str]]] = [
    (
        "lactose_sensitive",
        [
            "lactose", "bloating", "bloat", "gas", "indigestion", "stomach",
            "sensitive", "diarrhea", "acne", "digestion", "pimple", "upset",
        ],
    ),
    (
        "cutting_fat_loss",
        [
            "cut", "cutting", "fat loss", "weight loss", "lean", "calorie",
            "zero carb", "keto", "low carb", "abs",
        ],
    ),
    (
        "budget_value",
        [
            "budget", "cheap", "student", "under 1500", "under 1800", "under 2000",
            "affordable", "economical", "value", "cheapest", "pocket friendly",
        ],
    ),
    (
        "lab_purity",
        [
            "pure", "purest", "lab", "trustified", "labdoor", "heavy metal",
            "amino spike", "amino spiking", "genuine", "authentic", "fake", "blind test",
        ],
    ),
    (
        "stim_free",
        [
            "stim free", "caffeine free", "tingle", "tingles", "beta alanine",
            "night workout", "heart rate", "crash", "jitter", "jitters",
        ],
    ),
]


class SemanticFitnessSearch:
    """Semantic matcher connecting fitness goals to supplement attributes."""

    def detect_intents(self, user_query: str) -> List[FitnessIntent]:
        """Detect underlying health, dietary, or fitness intents from natural text."""
        query_lower = user_query.lower()
        words = set(re.findall(r"\b\w+\b", query_lower))

        detected: List[FitnessIntent] = []
        for intent_key, triggers in INTENT_TRIGGERS:
            for trigger in triggers:
                if trigger in query_lower or trigger in words:
                    intent = INTENT_KNOWLEDGE_BASE.get(intent_key)
                    if intent and intent not in detected:
                        detected.append(intent)
                    break
        return detected

    def score_product_fit(self, user_query: str, product_title: str) -> float:
        """Calculate semantic fitness compatibility score (0.0 to 1.0)."""
        intents = self.detect_intents(user_query)
        if not intents:
            return 0.5  # Neutral baseline

        title_lower = product_title.lower()
        score = 0.5

        for intent in intents:
            # Reward target attributes
            for attr in intent.target_attributes:
                if attr in title_lower:
                    score += 0.2

            # Penalize conflicting attributes
            for avoid in intent.avoid_attributes:
                if avoid in title_lower:
                    score -= 0.25

        return max(0.0, min(1.0, score))

    def get_intent_advice(self, user_query: str) -> Optional[str]:
        """Generate clinical / athletic advice based on detected dietary restriction."""
        intents = self.detect_intents(user_query)
        if not intents:
            return None
        return intents[0].explanation


semantic_search = SemanticFitnessSearch()
