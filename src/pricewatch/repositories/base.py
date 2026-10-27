"""Abstract repository interfaces for data access."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Tuple

from pricewatch.domain.models import (
    CanonicalListing,
    NotificationLog,
    PriceObservation,
    Subscription,
    User,
)


class BaseUserRepo(ABC):
    @abstractmethod
    async def get_or_create_user(
        self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None
    ) -> User:
        """Fetch existing user or create a new user profile."""

    @abstractmethod
    async def update_default_pincode(self, telegram_id: int, pincode: str) -> None:
        """Update user's default delivery pincode."""

    @abstractmethod
    async def deactivate_user(self, telegram_id: int) -> None:
        """Mark user as inactive when they block the bot."""

    @abstractmethod
    async def toggle_favourite_sku(self, telegram_id: int, sku: str) -> bool:
        """Toggle a product SKU in user's favourite list. Returns True if added, False if removed."""

    @abstractmethod
    async def update_user_settings(self, telegram_id: int, **kwargs) -> User:
        """Update user preferences and return updated User."""

    @abstractmethod
    async def get_all_active_users(self) -> List[User]:
        """Fetch all active registered users."""


class BaseListingRepo(ABC):
    @abstractmethod
    async def get_or_create_listing(self, listing: CanonicalListing) -> CanonicalListing:
        """Get existing canonical listing by (provider, product, variant, pincode) or insert new."""

    @abstractmethod
    async def get_listing_by_id(self, listing_id: int) -> Optional[CanonicalListing]:
        """Fetch single listing by primary key."""

    @abstractmethod
    async def claim_due_listings(
        self,
        worker_id: str,
        max_tier: int,
        min_tier: int = 1,
        batch_size: int = 25,
        lease_seconds: int = 300,
    ) -> List[CanonicalListing]:
        """Atomically claim a batch of due listings using FOR UPDATE SKIP LOCKED."""

    @abstractmethod
    async def update_listing_state(
        self,
        listing_id: int,
        last_price_paise: Optional[int],
        last_mrp_paise: Optional[int],
        last_available: Optional[bool],
        next_check_at: datetime,
        consecutive_failures: int = 0,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        canonical_url: Optional[str] = None,
    ) -> None:
        """Update listing price, scheduling state, and release worker lock."""

    @abstractmethod
    async def record_observation(self, observation: PriceObservation) -> None:
        """Record a historical price snapshot or daily heartbeat."""

    @abstractmethod
    async def get_price_observations(
        self, listing_id: int, limit: int = 50
    ) -> List[PriceObservation]:
        """Fetch historical price observations for a listing."""

    @abstractmethod
    async def get_active_listings_by_provider(
        self, provider_code: str
    ) -> List[CanonicalListing]:
        """Fetch all active and monitored listings for a given provider (e.g. 'amul')."""


class BaseSubscriptionRepo(ABC):
    @abstractmethod
    async def create_or_update_subscription(self, sub: Subscription) -> Subscription:
        """Create or update a user tracking subscription."""

    @abstractmethod
    async def get_user_subscriptions(
        self, telegram_id: int, active_only: bool = True
    ) -> List[Tuple[Subscription, CanonicalListing]]:
        """List all subscriptions and their associated listings for a given user."""

    @abstractmethod
    async def deactivate_subscription(self, telegram_id: int, listing_id: int) -> bool:
        """Untrack a product for a user."""

    @abstractmethod
    async def get_active_subscriptions_for_listing(self, listing_id: int) -> List[Subscription]:
        """Get all active subscriptions for a listing to evaluate alerts."""

    @abstractmethod
    async def update_alert_state(
        self,
        subscription_id: int,
        last_alerted_price_paise: Optional[int],
        alert_rearmed: bool,
    ) -> None:
        """Update subscription's last_alerted_price and re-arm state."""

    @abstractmethod
    async def log_notification(self, notif: NotificationLog) -> Optional[int]:
        """Insert notification into outbox ledger with idempotency deduplication."""
