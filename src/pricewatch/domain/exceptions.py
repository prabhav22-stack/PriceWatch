"""Domain exceptions for PriceWatch 2.0."""

from typing import Any, List, Optional


class PriceWatchError(Exception):
    """Base exception for all PriceWatch domain errors."""
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class VariantNotFoundError(PriceWatchError):
    """Raised when the specified variant ID was not found in the product listing."""


class VariantAmbiguousError(PriceWatchError):
    """Raised when a multi-variant product is tracked without an explicit variant_id."""
    def __init__(self, message: str, variants: Optional[List[Any]] = None):
        super().__init__(message, {"variants": variants or []})
        self.variants = variants or []


class ExtractionError(PriceWatchError):
    """Raised when parser fails to extract price, availability or product title."""


class BotBlockedError(PriceWatchError):
    """Raised when scraper encounters bot detection, CAPTCHA, or HTTP 403."""


class PincodeMismatchError(PriceWatchError):
    """Raised when verified page pincode does not match requested pincode."""


class PriceValidationError(PriceWatchError):
    """Raised when extracted price fails one of the validation gates."""


class ProductNotFoundError(PriceWatchError):
    """Raised when a product listing returns HTTP 404 or page not found."""


class UserBlockedBotError(PriceWatchError):
    """Raised when Telegram returns HTTP 403 (bot was blocked by the user)."""
