"""Domain enumerations for PriceWatch 2.0."""

from enum import Enum, IntEnum


class ProviderTier(IntEnum):
    """Extraction tier defining resource cost and execution environment."""
    API_OR_JSON = 1       # Fast Store JSON API (e.g. Shopify .js/.json)
    STRUCTURED_DATA = 2   # JSON-LD, OpenGraph, __NEXT_DATA__
    SCOPED_HTML = 3       # httpx + selectolax scoped DOM parser
    BROWSER = 4           # Playwright Chromium (Amazon Fresh / pincode-gated)


class AvailabilityStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class AlertType(str, Enum):
    TARGET_REACHED = "TARGET_REACHED"
    FURTHER_DROP = "FURTHER_DROP"
    RESTOCK_AT_TARGET = "RESTOCK_AT_TARGET"
    SIGNIFICANT_DROP = "SIGNIFICANT_DROP"
    AMUL_RESTOCK = "AMUL_RESTOCK"
    AMUL_STOCK_DECREASE = "AMUL_STOCK_DECREASE"
    AMUL_OUT_OF_STOCK = "AMUL_OUT_OF_STOCK"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"
    NEEDS_VERIFICATION_RETRY = "NEEDS_VERIFICATION_RETRY"


class CheckStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
