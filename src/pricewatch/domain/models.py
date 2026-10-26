"""Strongly-typed domain models and Data Transfer Objects (DTOs)."""

from datetime import datetime
from typing import Optional, Sequence
from pydantic import BaseModel, ConfigDict, Field

from pricewatch.domain.enums import (
    AlertType,
    NotificationStatus,
    ProviderTier,
    ValidationStatus,
)


class VariantOption(BaseModel):
    """Represents a specific product variant discovered during URL onboarding."""
    model_config = ConfigDict(frozen=True)

    external_variant_id: str
    variant_title: str
    canonical_url: str
    price_paise: Optional[int] = None
    mrp_paise: Optional[int] = None
    available: bool = True
    package_quantity: Optional[str] = None
    inventory_quantity: Optional[int] = None
    image_url: Optional[str] = None


class ResolutionResult(BaseModel):
    """Result of initial URL resolution during /track onboarding."""
    model_config = ConfigDict(frozen=True)

    provider_code: str
    provider_tier: ProviderTier
    external_product_id: str
    product_title: str
    requires_pincode: bool = False
    variants: Sequence[VariantOption]
    pinned_variant_id: Optional[str] = None  # None if multi-variant and URL lacks ?variant=
    image_url: Optional[str] = None


class PriceQuote(BaseModel):
    """Immutable price snapshot returned by a provider."""
    model_config = ConfigDict(frozen=True)

    external_product_id: str
    external_variant_id: str
    price_paise: Optional[int] = None
    mrp_paise: Optional[int] = None
    currency: str = "INR"
    available: bool = True
    verified_pincode: str = ""
    extraction_method: str
    seller_name: Optional[str] = None
    raw_variant_title: Optional[str] = None
    inventory_quantity: Optional[int] = None


class ValidationDecision(BaseModel):
    """Outcome of the 7-Gate PriceValidator."""
    model_config = ConfigDict(frozen=True)

    status: ValidationStatus
    gate_failed: Optional[int] = None
    reason: Optional[str] = None
    requires_retry: bool = False
    discount_pct: int = 0


class User(BaseModel):
    """User account linked to Telegram identity."""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    default_pincode: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CanonicalListing(BaseModel):
    """Single tracked store listing uniquely keyed by (provider, product, variant, pincode)."""
    id: Optional[int] = None
    provider_code: str
    provider_tier: int = 1
    external_product_id: str
    external_variant_id: str = "default"
    pincode: str = ""
    canonical_url: str
    product_title: str
    variant_title: Optional[str] = None
    package_quantity: Optional[str] = None
    currency: str = "INR"

    last_price_paise: Optional[int] = None
    last_mrp_paise: Optional[int] = None
    last_available: Optional[bool] = None
    inventory_quantity: Optional[int] = None
    last_seller_name: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    last_changed_at: Optional[datetime] = None

    is_monitored: bool = True
    check_interval_minutes: int = 30
    next_check_at: Optional[datetime] = None
    locked_until: Optional[datetime] = None
    lock_owner: Optional[str] = None
    consecutive_failures: int = 0
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Subscription(BaseModel):
    """Many-to-many subscription linking a User to a CanonicalListing."""
    id: Optional[int] = None
    telegram_id: int
    listing_id: int
    target_price_paise: int = Field(gt=0)
    notify_on_restock: bool = True
    notify_on_further_drop_pct: int = 2
    is_active: bool = True

    last_alerted_price_paise: Optional[int] = None
    last_alerted_at: Optional[datetime] = None
    alert_rearmed: bool = True

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PriceObservation(BaseModel):
    """Historical record of a price change or daily heartbeat."""
    id: Optional[int] = None
    listing_id: int
    price_paise: Optional[int] = None
    mrp_paise: Optional[int] = None
    available: bool = True
    seller_name: Optional[str] = None
    extraction_method: str
    is_verified: bool = True
    observed_at: Optional[datetime] = None


class NotificationLog(BaseModel):
    """Transactional outbox ledger for Telegram alerts."""
    id: Optional[int] = None
    subscription_id: int
    observation_id: Optional[int] = None
    alert_type: AlertType
    price_paise: int
    idempotency_key: str
    status: NotificationStatus = NotificationStatus.PENDING
    telegram_message_id: Optional[int] = None
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    error_detail: Optional[str] = None
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
