"""Automated Store Coupon Extractor.

Extracts on-page checkout coupons (Amazon "Apply ₹X coupon" checkboxes,
Flipkart special discounts, and Brand Direct promo codes) to compute
the real effective checkout price without bank cards.
"""

from dataclasses import dataclass
import re
from typing import Optional

from pricewatch.logging_setup import get_logger

logger = get_logger("services.coupon_service")


@dataclass
class CouponInfo:
    """Extracted store coupon details."""
    has_coupon: bool = False
    discount_amount: float = 0.0
    discount_pct: Optional[float] = None
    coupon_code: Optional[str] = None
    description: str = ""
    effective_price: float = 0.0


# Regex patterns for on-page coupons across Amazon, Flipkart, and Shopify stores
RUPEE_COUPON_PATTERN = re.compile(
    r"(?:apply|save|flat|get|extra|for)?\s*(?:extra\s*)?(?:₹|rs\.?)\s*(\d+(?:\.\d+)?)\s*(?:off|with\s+(?:the\s+)?coupon|coupon|voucher)",
    re.IGNORECASE,
)
PCT_COUPON_PATTERN = re.compile(
    r"(?:apply|save|get|extra|for)?\s*(?:extra\s*)?(\d+)%\s*(?:off|with\s+(?:the\s+)?coupon|coupon|voucher)",
    re.IGNORECASE,
)
CODE_COUPON_PATTERN = re.compile(
    r"(?:use\s*code|coupon:?|promo:?)\s*([A-Z0-9_-]{3,15})",
    re.IGNORECASE,
)


class CouponExtractorService:
    """Detects and calculates store coupon discounts."""

    def extract_coupon(self, text_or_html: str, current_price: float) -> CouponInfo:
        """Extract coupon details from page text or store snippet."""
        if not text_or_html or current_price <= 0:
            return CouponInfo(effective_price=current_price)

        clean = text_or_html.replace("\n", " ").strip()

        # 1. Match fixed Rupee discounts (e.g. "Apply ₹200 coupon")
        rupee_match = RUPEE_COUPON_PATTERN.search(clean)
        if rupee_match:
            try:
                amount = float(rupee_match.group(1))
                if 20 <= amount < current_price:
                    code_match = CODE_COUPON_PATTERN.search(clean)
                    code = code_match.group(1) if code_match else None
                    eff = max(0.0, current_price - amount)
                    desc = f"Save ₹{amount:,.0f} with on-page coupon"
                    if code:
                        desc += f" (Code: {code})"
                    else:
                        desc += ' (Check "Apply Coupon" box)'
                    return CouponInfo(
                        has_coupon=True,
                        discount_amount=amount,
                        coupon_code=code,
                        description=desc,
                        effective_price=eff,
                    )
            except ValueError:
                pass

        # 2. Match Percentage discounts (e.g. "Save 10% with coupon")
        pct_match = PCT_COUPON_PATTERN.search(clean)
        if pct_match:
            try:
                pct = float(pct_match.group(1))
                if 1 <= pct <= 50:
                    amount = round(current_price * (pct / 100.0), 2)
                    code_match = CODE_COUPON_PATTERN.search(clean)
                    code = code_match.group(1) if code_match else None
                    eff = max(0.0, current_price - amount)
                    desc = f"Save {pct:.0f}% (₹{amount:,.0f}) with coupon"
                    if code:
                        desc += f" (Code: {code})"
                    else:
                        desc += ' (Check "Apply Coupon" box)'
                    return CouponInfo(
                        has_coupon=True,
                        discount_amount=amount,
                        discount_pct=pct,
                        coupon_code=code,
                        description=desc,
                        effective_price=eff,
                    )
            except ValueError:
                pass

        return CouponInfo(effective_price=current_price)

    def format_coupon_markdown(self, coupon: CouponInfo) -> str:
        """Format coupon callout for Telegram Markdown / HTML."""
        if not coupon.has_coupon or coupon.discount_amount <= 0:
            return ""
        return (
            f"🏷️ <b>Active Coupon:</b> {coupon.description}\n"
            f"💰 <b>Effective Price:</b> ₹{coupon.effective_price:,.0f}\n"
        )


coupon_service = CouponExtractorService()
