"""Normalizer for Indian currency formats and price strings to integer paise."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


# Pattern to strip out non-numeric characters except dots and commas
_CURRENCY_SYMBOLS = re.compile(r"[₹\$\€\£\s]|Rs\.?|INR", re.IGNORECASE)


def parse_inr_to_paise(raw_value: Any) -> Optional[int]:
    """
    Convert any Indian price representation to integer paise.
    
    Examples:
        - "₹ 1,24,999.50" -> 12499950
        - "₹1,499.00"     -> 149900
        - "Rs. 499"       -> 49900
        - 1499            -> 149900 (treated as rupees if integer < 10,000, or explicitly handle context)
        - "1,499"         -> 149900
        - 1499.5          -> 149950
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, int):
        # Already an integer; assume rupees
        return raw_value * 100

    if isinstance(raw_value, float):
        return int(round(raw_value * 100))

    if isinstance(raw_value, Decimal):
        return int(round(raw_value * 100))

    text = str(raw_value).strip()
    if not text:
        return None

    # Clean currency symbols
    cleaned = _CURRENCY_SYMBOLS.sub("", text)

    # Remove commas used as thousands separators in both Indian (1,24,999) and Western (124,999) formats
    cleaned = cleaned.replace(",", "").strip()

    if not cleaned:
        return None

    try:
        dec = Decimal(cleaned)
        # Multiply by 100 to get paise
        paise = int(round(dec * 100))
        return paise if paise >= 0 else None
    except InvalidOperation:
        return None


def format_paise_to_inr(paise: Optional[int], include_symbol: bool = True) -> str:
    """
    Format integer paise into Indian currency representation with proper commas.
    
    Examples:
        - 12499950 -> "₹1,24,999.50"
        - 149900   -> "₹1,499"
        - 49900    -> "₹499"
    """
    if paise is None:
        return "N/A"

    rupees = paise // 100
    fraction = paise % 100

    # Indian comma grouping algorithm for integer part
    s = str(rupees)
    if len(s) > 3:
        last_three = s[-3:]
        remaining = s[:-3]
        # Group remaining in twos
        groups = []
        while remaining:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        groups.reverse()
        formatted_int = ",".join(groups) + "," + last_three
    else:
        formatted_int = s

    if fraction > 0:
        formatted = f"{formatted_int}.{fraction:02d}"
    else:
        formatted = formatted_int

    prefix = "₹" if include_symbol else ""
    return f"{prefix}{formatted}"
