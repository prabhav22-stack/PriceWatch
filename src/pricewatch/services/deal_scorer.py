"""Deal Quality and Deceptive MRP / Fake Discount Detection Engine.

Inspired by open-source price monitoring engines (PriceDive, PriceRadar).
Evaluates true discounts versus artificially inflated MRPs across Indian e-commerce.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DealEvaluation:
    deal_score: int              # 1 to 10
    rating_label: str            # e.g. "💎 All-Time Low", "⚠️ Fake Discount"
    is_fake_discount: bool       # True if merchant artificially marked up MRP
    mrp_inflation_pct: float     # Percentage by which MRP exceeds typical baseline
    savings_vs_avg_paise: int    # Paise saved compared to 30-day average
    summary: str                 # Human-friendly explanation


class DealScorer:
    """Evaluates whether a discount is genuine or deceptive based on price history."""

    @staticmethod
    def evaluate_deal(
        current_price_paise: int,
        mrp_paise: Optional[int],
        history_summary_30d: Optional[dict] = None,
    ) -> DealEvaluation:
        """
        Evaluate deal score and detect fake markdowns.

        Parameters:
            current_price_paise: Current selling price in paise.
            mrp_paise: Displayed strikethrough MRP in paise.
            history_summary_30d: Dict with 'min_price', 'max_price', 'avg_price', 'median_price', 'count'.
        """
        if current_price_paise <= 0:
            return DealEvaluation(
                deal_score=5,
                rating_label="⚪ Normal Price",
                is_fake_discount=False,
                mrp_inflation_pct=0.0,
                savings_vs_avg_paise=0,
                summary="Insufficient pricing data to evaluate deal.",
            )

        # Baseline: If no historical data available yet
        if not history_summary_30d or not history_summary_30d.get("avg_price"):
            claimed_disc = 0.0
            if mrp_paise and mrp_paise > current_price_paise:
                claimed_disc = ((mrp_paise - current_price_paise) / mrp_paise) * 100.0

            if claimed_disc >= 30:
                score = 8
                label = f"🟢 Good Deal ({int(claimed_disc)}% off MRP)"
            elif claimed_disc >= 15:
                score = 7
                label = f"🟢 Fair Deal ({int(claimed_disc)}% off MRP)"
            else:
                score = 6
                label = "⚪ Standard Store Price"

            return DealEvaluation(
                deal_score=score,
                rating_label=label,
                is_fake_discount=False,
                mrp_inflation_pct=0.0,
                savings_vs_avg_paise=0,
                summary=f"Claimed discount of {claimed_disc:.0f}% off MRP (Historical baseline accumulating).",
            )

        min_price = history_summary_30d.get("min_price", current_price_paise)
        max_price = history_summary_30d.get("max_price", current_price_paise)
        avg_price = history_summary_30d.get("avg_price", current_price_paise)
        median_price = history_summary_30d.get("median_price", avg_price)

        savings_vs_avg = avg_price - current_price_paise
        savings_pct_vs_avg = (savings_vs_avg / avg_price) * 100.0 if avg_price > 0 else 0.0

        # Check for MRP inflation (Fake Discount detection)
        # If MRP is more than 35% higher than the maximum historical price, seller is likely exaggerating discount
        is_fake = False
        mrp_inflation = 0.0
        if mrp_paise and max_price > 0 and mrp_paise > (max_price * 1.30):
            mrp_inflation = ((mrp_paise - max_price) / max_price) * 100.0
            # If current price is not actually cheaper than median price, it's a deceptive sale
            if current_price_paise >= median_price:
                is_fake = True

        # Score computation
        if current_price_paise <= min_price:
            score = 10
            label = "💎 Historic Low (10/10)"
            summary = f"Lowest price recorded in 30 days! ₹{savings_vs_avg / 100:,.0f} below 30-day average."
        elif savings_pct_vs_avg >= 15:
            score = 9
            label = "🔥 Epic Deal (9/10)"
            summary = f"Significant drop! {savings_pct_vs_avg:.0f}% cheaper than 30-day average (Save ₹{savings_vs_avg / 100:,.0f})."
        elif savings_pct_vs_avg >= 7:
            score = 8
            label = "🟢 Great Price (8/10)"
            summary = f"Good discount: ₹{savings_vs_avg / 100:,.0f} below normal 30-day median."
        elif is_fake:
            score = 3
            label = "⚠️ Fake Discount Alert (3/10)"
            summary = f"Deceptive MRP markup detected! Listed MRP was inflated by {mrp_inflation:.0f}%, while selling price is near average."
        elif abs(savings_pct_vs_avg) <= 5:
            score = 6
            label = "🟡 Fair Price (6/10)"
            summary = "Near typical 30-day price range. No unusual discount."
        else:
            # Price is higher than average
            score = 4
            overpay = current_price_paise - avg_price
            label = "🔴 Expensive (4/10)"
            summary = f"Currently ₹{overpay / 100:,.0f} higher than 30-day average. Recommend waiting for a drop."

        return DealEvaluation(
            deal_score=score,
            rating_label=label,
            is_fake_discount=is_fake,
            mrp_inflation_pct=round(mrp_inflation, 1),
            savings_vs_avg_paise=max(0, savings_vs_avg),
            summary=summary,
        )
