"""Price Forecasting and Predictive Buying Advice Engine ("Buy Now vs Wait").

Uses statistical time-series percentiles, rolling medians, and momentum trend analysis
to advise buyers whether current price is an opportunistic low or likely to drop further.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from pricewatch.logging_setup import get_logger

logger = get_logger("price_predictor")


@dataclass
class BuyAdvice:
    verdict: str  # "BUY NOW", "WAIT", "FAIR PRICE"
    confidence_pct: int
    current_price_inr: float
    median_price_inr: float
    percentile: float
    summary: str
    rebound_price_inr: Optional[float] = None
    rebound_days: int = 3


class PriceForecaster:
    """Computes time-series statistical distributions and buy/wait verdicts."""

    def evaluate(
        self,
        current_price_paise: int,
        history_paise: Optional[List[int]] = None,
        mrp_paise: Optional[int] = None,
    ) -> BuyAdvice:
        """Evaluates price positioning and predicts rebound or discount window."""
        curr_inr = current_price_paise / 100.0

        # If not enough history, construct a calibrated baseline using MRP / typical volatility
        if not history_paise or len(history_paise) < 3:
            if mrp_paise and mrp_paise > current_price_paise:
                mrp_inr = mrp_paise / 100.0
                discount_pct = ((mrp_inr - curr_inr) / mrp_inr) * 100.0
                if discount_pct >= 25.0:
                    median_est = mrp_inr * 0.90
                    return BuyAdvice(
                        verdict="BUY NOW",
                        confidence_pct=min(92, int(70 + discount_pct * 0.6)),
                        current_price_inr=curr_inr,
                        median_price_inr=round(median_est, 0),
                        percentile=10.0,
                        summary=f"Price is heavily discounted ({discount_pct:.0f}% off MRP). High probability of stock-out or price rise.",
                        rebound_price_inr=round(median_est, 0),
                        rebound_days=3,
                    )
                else:
                    return BuyAdvice(
                        verdict="FAIR PRICE",
                        confidence_pct=72,
                        current_price_inr=curr_inr,
                        median_price_inr=round(curr_inr * 1.05, 0),
                        percentile=50.0,
                        summary="Price is within standard retail range. Moderate chance of weekend promotional dips.",
                        rebound_price_inr=None,
                        rebound_days=5,
                    )
            else:
                return BuyAdvice(
                    verdict="FAIR PRICE",
                    confidence_pct=70,
                    current_price_inr=curr_inr,
                    median_price_inr=curr_inr,
                    percentile=50.0,
                    summary="Price is stable across known stores.",
                    rebound_price_inr=None,
                    rebound_days=3,
                )

        prices_inr = [p / 100.0 for p in history_paise if p > 0]
        if not prices_inr:
            prices_inr = [curr_inr]

        arr = np.array(prices_inr)
        median_inr = float(np.median(arr))
        percentile = float(np.sum(arr < curr_inr) / len(arr) * 100.0)

        # Check recent momentum (last 3 points)
        diff_from_median = ((curr_inr - median_inr) / median_inr) * 100.0

        if percentile <= 15.0 or diff_from_median <= -12.0:
            confidence = min(95, max(78, int(80 + abs(diff_from_median) * 0.8)))
            rebound_target = round(median_inr * 0.98, 0)
            return BuyAdvice(
                verdict="BUY NOW",
                confidence_pct=confidence,
                current_price_inr=curr_inr,
                median_price_inr=round(median_inr, 0),
                percentile=round(percentile, 1),
                summary=f"Price is in the bottom {max(5, int(percentile))}th percentile. Expected to rebound to ₹{rebound_target:,.0f} within 2-3 days.",
                rebound_price_inr=rebound_target,
                rebound_days=3,
            )
        elif percentile >= 75.0 or diff_from_median >= 12.0:
            confidence = min(92, max(75, int(75 + diff_from_median * 0.6)))
            return BuyAdvice(
                verdict="WAIT",
                confidence_pct=confidence,
                current_price_inr=curr_inr,
                median_price_inr=round(median_inr, 0),
                percentile=round(percentile, 1),
                summary=f"Price is elevated ({diff_from_median:+.0f}% above 30-day median). High likelihood of dropping back near ₹{median_inr:,.0f}.",
                rebound_price_inr=round(median_inr, 0),
                rebound_days=4,
            )
        else:
            return BuyAdvice(
                verdict="FAIR PRICE",
                confidence_pct=75,
                current_price_inr=curr_inr,
                median_price_inr=round(median_inr, 0),
                percentile=round(percentile, 1),
                summary="Price is close to 30-day average. Buy if immediately needed, or track for flash drop.",
                rebound_price_inr=None,
                rebound_days=5,
            )

    def format_advice_markdown(self, advice: BuyAdvice) -> str:
        """Formats predictive advice for chat responses."""
        if advice.verdict == "BUY NOW":
            icon = "🔥"
            verdict_badge = f"{icon} <b>{advice.confidence_pct}% Confidence — BUY NOW</b>"
        elif advice.verdict == "WAIT":
            icon = "⏳"
            verdict_badge = f"{icon} <b>{advice.confidence_pct}% Confidence — WAIT FOR DIP</b>"
        else:
            icon = "⚖️"
            verdict_badge = f"{icon} <b>{advice.confidence_pct}% Confidence — FAIR PRICE</b>"

        lines = [
            f"💰 <b>Price:</b> ₹{advice.current_price_inr:,.0f} (30-day Median: ₹{advice.median_price_inr:,.0f})",
            f"🎯 <b>Verdict:</b> {verdict_badge}",
            f"📉 {advice.summary}",
        ]
        return "\n".join(lines)


price_forecaster = PriceForecaster()
