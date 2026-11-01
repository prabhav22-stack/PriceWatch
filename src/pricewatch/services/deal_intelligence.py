"""Deal Intelligence and Fake Discount Detection Engine.

Inspired by amazon-buddy (drawrowfly/amazon-buddy) patterns for e-commerce
deal scoring, true discount calculation, and inflated MRP detection.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from pricewatch.validation.normalizer import format_paise_to_inr


@dataclass(frozen=True)
class DealScore:
    score: float  # 1.0 to 10.0
    verdict: str  # e.g. "🔥 STEAL DEAL", "⚡ GREAT DEAL", "👍 FAIR PRICE", "⚠️ INFLATED MRP"
    real_discount_pct: int
    is_fake_discount: bool
    summary: str
    badge: str


class DealIntelligenceService:
    """Evaluates e-commerce deals, detects artificial MRP markup, and scores deal quality."""

    @staticmethod
    def evaluate_deal(
        selling_price_paise: int,
        mrp_paise: Optional[int] = None,
        all_store_prices_paise: Optional[List[int]] = None,
        lowest_historical_paise: Optional[int] = None,
    ) -> DealScore:
        """Evaluate deal quality, detect fake discounts, and assign a 1-10 deal rating."""
        if selling_price_paise <= 0:
            return DealScore(
                score=5.0,
                verdict="🏷️ REGULAR",
                real_discount_pct=0,
                is_fake_discount=False,
                summary="Standard pricing",
                badge="🏷️",
            )

        # 1. Benchmark reference price
        ref_prices = [p for p in (all_store_prices_paise or []) if p > 0]
        if not ref_prices and mrp_paise:
            ref_prices = [mrp_paise]

        median_market_price = (
            sorted(ref_prices)[len(ref_prices) // 2] if ref_prices else selling_price_paise
        )

        # 2. Check for fake / inflated MRP
        # An MRP is marked as inflated if it's more than 60% higher than the median market price
        is_fake_discount = False
        if mrp_paise and median_market_price > 0:
            mrp_markup_ratio = mrp_paise / median_market_price
            if mrp_markup_ratio > 1.65:
                is_fake_discount = True

        # 3. Real discount calculation vs median market benchmark
        benchmark_price = mrp_paise if (mrp_paise and not is_fake_discount) else median_market_price
        if benchmark_price > selling_price_paise:
            real_discount_pct = int(round((benchmark_price - selling_price_paise) * 100.0 / benchmark_price))
        else:
            real_discount_pct = 0

        # 4. Deal Quality Scoring (1.0 to 10.0)
        score = 5.0

        # Advantage over market median
        if median_market_price > selling_price_paise:
            market_saving_pct = (median_market_price - selling_price_paise) / median_market_price
            score += min(3.0, market_saving_pct * 10)  # up to +3.0
        elif selling_price_paise > median_market_price:
            market_overpay_pct = (selling_price_paise - median_market_price) / median_market_price
            score -= min(2.5, market_overpay_pct * 8)

        # Advantage over historical low
        if lowest_historical_paise and lowest_historical_paise > 0:
            if selling_price_paise <= lowest_historical_paise:
                score += 1.5  # At or below all-time low
            elif selling_price_paise <= lowest_historical_paise * 1.05:
                score += 0.8  # Within 5% of all-time low

        # Fake discount penalty
        if is_fake_discount:
            score = min(score, 6.0)

        score = round(max(1.0, min(10.0, score)), 1)

        # 5. Determine Verdict and Summary
        if score >= 8.5:
            verdict = "🔥 STEAL DEAL"
            badge = "🔥"
            summary = f"Exceptional price! {real_discount_pct}% below benchmark"
        elif score >= 7.0:
            verdict = "⚡ GREAT DEAL"
            badge = "⚡"
            summary = f"Solid savings ({real_discount_pct}% off market average)"
        elif is_fake_discount:
            verdict = "⚠️ INFLATED MRP"
            badge = "⚠️"
            summary = "Seller artificially inflated MRP to exaggerate discount"
        elif score >= 5.5:
            verdict = "👍 FAIR PRICE"
            badge = "👍"
            summary = "Competitive market rate"
        else:
            verdict = "📈 ABOVE AVERAGE"
            badge = "📈"
            summary = "Priced slightly above current market average"

        return DealScore(
            score=score,
            verdict=verdict,
            real_discount_pct=real_discount_pct,
            is_fake_discount=is_fake_discount,
            summary=summary,
            badge=badge,
        )


deal_intelligence = DealIntelligenceService()
