"""In-chat UTF-8 text sparklines inspired by holman/spark.

Generates zero-bandwidth, instant visual sparkline charts using Unicode block
characters ( ▂▃▄▅▆▇█) that render flawlessly in all Telegram clients.
"""

from typing import List, Optional, Sequence, Union

_TICKS = (" ", "▂", "▃", "▄", "▅", "▆", "▇", "█")


def generate_sparkline(
    values: Sequence[Union[int, float]],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> str:
    """Generate a Unicode sparkline string for a sequence of numeric data points.

    Args:
        values: Sequence of numeric values (e.g. price observations over time).
        min_val: Optional explicit minimum bound.
        max_val: Optional explicit maximum bound.

    Returns:
        String of Unicode block characters representing the trend.
    """
    if not values:
        return ""

    num_vals = [float(v) for v in values]
    lo = min_val if min_val is not None else min(num_vals)
    hi = max_val if max_val is not None else max(num_vals)

    spread = hi - lo
    if spread <= 0.0001:
        # Flat line: return middle tick
        return _TICKS[3] * len(num_vals)

    res = []
    ticks_len = len(_TICKS)
    for v in num_vals:
        # Clamp to bounds
        clamped = max(lo, min(hi, v))
        # Map to 0..ticks_len - 1
        idx = int((clamped - lo) / spread * (ticks_len - 1))
        idx = max(0, min(ticks_len - 1, idx))
        res.append(_TICKS[idx])

    return "".join(res)


def format_price_trend_summary(
    prices_paise: Sequence[int],
    current_price_paise: Optional[int] = None,
) -> Optional[str]:
    """Format an informative inline trend summary with sparkline, min, max, and direction."""
    if not prices_paise or len(prices_paise) < 2:
        return None

    rupees = [p / 100.0 for p in prices_paise]
    curr = (current_price_paise / 100.0) if current_price_paise is not None else rupees[-1]
    spark = generate_sparkline(rupees)

    min_p = min(rupees)
    max_p = max(rupees)
    first_p = rupees[0]

    direction = "➡️"
    if curr < first_p * 0.98:
        direction = "📉 Dropping"
    elif curr > first_p * 1.02:
        direction = "📈 Rising"
    else:
        direction = "⚖️ Stable"

    is_atl = curr <= min_p
    badge = " 🏆 <b>All-Time Low!</b>" if is_atl else ""

    return (
        f"📊 <b>Price Trend:</b> <code>{spark}</code> ({direction}{badge})\n"
        f"   <i>Low: ₹{min_p:,.0f} | High: ₹{max_p:,.0f} | Latest: ₹{curr:,.0f}</i>"
    )
