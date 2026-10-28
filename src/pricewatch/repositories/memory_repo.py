"""In-memory repository implementation for unit testing and offline development."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pricewatch.domain.models import (
    CanonicalListing,
    NotificationLog,
    PriceObservation,
    Subscription,
    User,
)
from pricewatch.repositories.base import (
    BaseListingRepo,
    BaseSubscriptionRepo,
    BaseUserRepo,
)


class MemoryRepository(BaseUserRepo, BaseListingRepo, BaseSubscriptionRepo):
    """Thread-safe in-memory data store replicating PostgreSQL behavior."""

    def __init__(self):
        self.users: Dict[int, User] = {}
        self.listings: Dict[int, CanonicalListing] = {}
        self.subscriptions: Dict[int, Subscription] = {}
        self.observations: List[PriceObservation] = []
        self.notifications: Dict[int, NotificationLog] = {}
        self.idempotency_keys: set = set()

        self._listing_seq = 1
        self._sub_seq = 1
        self._obs_seq = 1
        self._notif_seq = 1

    # --- User Repo ---
    async def get_or_create_user(
        self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None
    ) -> User:
        if telegram_id not in self.users:
            self.users[telegram_id] = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        return self.users[telegram_id]

    async def update_default_pincode(self, telegram_id: int, pincode: str) -> None:
        user = await self.get_or_create_user(telegram_id)
        self.users[telegram_id] = user.model_copy(update={"default_pincode": pincode})

    async def deactivate_user(self, telegram_id: int) -> None:
        if telegram_id in self.users:
            self.users[telegram_id] = self.users[telegram_id].model_copy(update={"is_active": False})
        for sub_id, sub in list(self.subscriptions.items()):
            if sub.telegram_id == telegram_id:
                self.subscriptions[sub_id] = sub.model_copy(update={"is_active": False})

    async def toggle_favourite_sku(self, telegram_id: int, sku: str) -> bool:
        user = await self.get_or_create_user(telegram_id)
        favs = list(user.favourite_skus or [])
        if sku in favs:
            favs.remove(sku)
            added = False
        else:
            favs.append(sku)
            added = True
        self.users[telegram_id] = user.model_copy(update={"favourite_skus": favs})
        return added

    async def update_user_settings(self, telegram_id: int, **kwargs) -> User:
        user = await self.get_or_create_user(telegram_id)
        updated = user.model_copy(update=kwargs)
        self.users[telegram_id] = updated
        return updated

    async def get_all_active_users(self) -> List[User]:
        return [u for u in self.users.values() if u.is_active]

    # --- Listing Repo ---
    async def get_or_create_listing(self, listing: CanonicalListing) -> CanonicalListing:
        for existing in self.listings.values():
            if (
                existing.provider_code == listing.provider_code
                and existing.external_product_id == listing.external_product_id
                and existing.external_variant_id == listing.external_variant_id
                and existing.pincode == listing.pincode
            ):
                return existing

        new_id = self._listing_seq
        self._listing_seq += 1
        saved = listing.model_copy(
            update={
                "id": new_id,
                "created_at": datetime.now(timezone.utc),
                "next_check_at": datetime.now(timezone.utc),
            }
        )
        self.listings[new_id] = saved
        return saved

    async def get_listing_by_id(self, listing_id: int) -> Optional[CanonicalListing]:
        return self.listings.get(listing_id)

    async def claim_due_listings(
        self,
        worker_id: str,
        max_tier: int,
        min_tier: int = 1,
        batch_size: int = 25,
        lease_seconds: int = 300,
    ) -> List[CanonicalListing]:
        now = datetime.now(timezone.utc)
        claimed = []
        for l in self.listings.values():
            if not l.is_monitored:
                continue
            if not (min_tier <= l.provider_tier <= max_tier):
                continue
            if l.next_check_at and l.next_check_at > now:
                continue
            if l.locked_until and l.locked_until > now:
                continue

            claimed.append(l)
            if len(claimed) >= batch_size:
                break

        # Apply lease lock
        from datetime import timedelta
        lease_time = now + timedelta(seconds=lease_seconds)
        result = []
        for l in claimed:
            updated = l.model_copy(update={"locked_until": lease_time, "lock_owner": worker_id})
            self.listings[l.id] = updated
            result.append(updated)
        return result

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
        if listing_id in self.listings:
            l = self.listings[listing_id]
            updates = {
                "last_price_paise": last_price_paise,
                "last_mrp_paise": last_mrp_paise,
                "last_available": last_available,
                "last_checked_at": datetime.now(timezone.utc),
                "next_check_at": next_check_at,
                "locked_until": None,
                "lock_owner": None,
                "consecutive_failures": consecutive_failures,
                "last_error_code": error_code,
                "last_error_message": error_message,
            }
            if canonical_url:
                updates["canonical_url"] = canonical_url
            self.listings[listing_id] = l.model_copy(update=updates)

    async def record_observation(self, observation: PriceObservation) -> None:
        obs_id = self._obs_seq
        self._obs_seq += 1
        obs = observation.model_copy(update={"id": obs_id, "observed_at": datetime.now(timezone.utc)})
        self.observations.append(obs)

    async def get_price_observations(
        self, listing_id: int, limit: int = 50
    ) -> List[PriceObservation]:
        matching = [o for o in self.observations if o.listing_id == listing_id]
        matching.sort(key=lambda o: o.observed_at or datetime.min)
        return matching[-limit:]

    async def get_price_history_since(
        self, listing_id: int, since: datetime
    ) -> List[PriceObservation]:
        matching = [
            o for o in self.observations
            if o.listing_id == listing_id and (o.observed_at is None or o.observed_at >= since)
        ]
        matching.sort(key=lambda o: o.observed_at or datetime.min)
        return matching

    async def get_30d_price_summary(
        self, listing_id: int
    ) -> Optional[dict]:
        from datetime import timedelta
        import statistics
        since = datetime.now(timezone.utc) - timedelta(days=30)
        observations = await self.get_price_history_since(listing_id, since)
        prices = [o.price_paise for o in observations if o.price_paise is not None and o.price_paise > 0]
        if not prices:
            return None
        return {
            "min_price": min(prices),
            "max_price": max(prices),
            "avg_price": sum(prices) // len(prices),
            "median_price": int(statistics.median(prices)),
            "count": len(prices),
        }

    async def get_active_listings_by_provider(
        self, provider_code: str
    ) -> List[CanonicalListing]:
        return [
            l for l in self.listings.values()
            if l.provider_code == provider_code and l.is_monitored
        ]

    # --- Subscription Repo ---
    async def create_or_update_subscription(self, sub: Subscription) -> Subscription:
        for s_id, existing in self.subscriptions.items():
            if existing.telegram_id == sub.telegram_id and existing.listing_id == sub.listing_id:
                updated = existing.model_copy(
                    update={
                        "target_price_paise": sub.target_price_paise,
                        "is_active": True,
                        "alert_rearmed": True,
                    }
                )
                self.subscriptions[s_id] = updated
                return updated

        new_id = self._sub_seq
        self._sub_seq += 1
        saved = sub.model_copy(update={"id": new_id, "created_at": datetime.now(timezone.utc)})
        self.subscriptions[new_id] = saved
        return saved

    async def get_user_subscriptions(
        self, telegram_id: int, active_only: bool = True
    ) -> List[Tuple[Subscription, CanonicalListing]]:
        result = []
        for s in self.subscriptions.values():
            if s.telegram_id == telegram_id:
                if active_only and not s.is_active:
                    continue
                listing = self.listings.get(s.listing_id)
                if listing:
                    result.append((s, listing))
        return result

    async def deactivate_subscription(self, telegram_id: int, listing_id: int) -> bool:
        for s_id, s in self.subscriptions.items():
            if s.telegram_id == telegram_id and s.listing_id == listing_id:
                self.subscriptions[s_id] = s.model_copy(update={"is_active": False})
                return True
        return False

    async def get_active_subscriptions_for_listing(self, listing_id: int) -> List[Subscription]:
        return [s for s in self.subscriptions.values() if s.listing_id == listing_id and s.is_active]

    async def update_alert_state(
        self,
        subscription_id: int,
        last_alerted_price_paise: Optional[int],
        alert_rearmed: bool,
    ) -> None:
        if subscription_id in self.subscriptions:
            s = self.subscriptions[subscription_id]
            self.subscriptions[subscription_id] = s.model_copy(
                update={
                    "last_alerted_price_paise": last_alerted_price_paise,
                    "last_alerted_at": datetime.now(timezone.utc),
                    "alert_rearmed": alert_rearmed,
                }
            )

    async def log_notification(self, notif: NotificationLog) -> Optional[int]:
        if notif.idempotency_key in self.idempotency_keys:
            # Duplicate alert suppressed
            return None

        self.idempotency_keys.add(notif.idempotency_key)
        new_id = self._notif_seq
        self._notif_seq += 1
        saved = notif.model_copy(update={"id": new_id, "created_at": datetime.now(timezone.utc)})
        self.notifications[new_id] = saved
        return new_id
