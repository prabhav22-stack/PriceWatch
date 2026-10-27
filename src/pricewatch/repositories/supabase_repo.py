"""Supabase / PostgreSQL repository adapter."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client, create_client

from pricewatch.config import settings
from pricewatch.domain.enums import AlertType, NotificationStatus
from pricewatch.domain.models import (
    CanonicalListing,
    NotificationLog,
    PriceObservation,
    Subscription,
    User,
)
from pricewatch.logging_setup import get_logger
from pricewatch.repositories.base import (
    BaseListingRepo,
    BaseSubscriptionRepo,
    BaseUserRepo,
)

logger = get_logger("supabase_repo")


class SupabaseRepository(BaseUserRepo, BaseListingRepo, BaseSubscriptionRepo):
    """Production data access adapter powered by Supabase."""

    def __init__(self, client: Optional[Client] = None):
        if client:
            self.client = client
        else:
            url = settings.SUPABASE_URL
            key = settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN
            if not url or not key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY must be configured")
            self.client = create_client(url, key)

    # --- User Repo ---
    async def get_or_create_user(
        self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None
    ) -> User:
        data = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        resp = self.client.table("users").upsert(data, on_conflict="telegram_id").execute()
        row = resp.data[0] if resp.data else data
        return User(**row)

    async def update_default_pincode(self, telegram_id: int, pincode: str) -> None:
        self.client.table("users").update({"default_pincode": pincode}).eq("telegram_id", telegram_id).execute()

    async def deactivate_user(self, telegram_id: int) -> None:
        self.client.table("users").update({"is_active": False}).eq("telegram_id", telegram_id).execute()
        self.client.table("subscriptions").update({"is_active": False}).eq("telegram_id", telegram_id).execute()

    async def toggle_favourite_sku(self, telegram_id: int, sku: str) -> bool:
        user = await self.get_or_create_user(telegram_id)
        favs = list(user.favourite_skus or [])
        if sku in favs:
            favs.remove(sku)
            added = False
        else:
            favs.append(sku)
            added = True
        self.client.table("users").update(
            {"favourite_skus": favs, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("telegram_id", telegram_id).execute()
        return added

    async def update_user_settings(self, telegram_id: int, **kwargs) -> User:
        payload = dict(kwargs)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = self.client.table("users").update(payload).eq("telegram_id", telegram_id).execute()
        row = res.data[0] if res.data else None
        if row:
            return User(**row)
        return await self.get_or_create_user(telegram_id)

    async def get_all_active_users(self) -> List[User]:
        res = self.client.table("users").select("*").eq("is_active", True).execute()
        return [User(**row) for row in res.data]

    # --- Listing Repo ---
    async def get_or_create_listing(self, listing: CanonicalListing) -> CanonicalListing:
        query = (
            self.client.table("canonical_listings")
            .select("*")
            .eq("provider_code", listing.provider_code)
            .eq("external_product_id", listing.external_product_id)
            .eq("external_variant_id", listing.external_variant_id)
            .eq("pincode", listing.pincode)
            .execute()
        )
        if query.data:
            return CanonicalListing(**query.data[0])

        payload = {
            "provider_code": listing.provider_code,
            "provider_tier": listing.provider_tier,
            "external_product_id": listing.external_product_id,
            "external_variant_id": listing.external_variant_id,
            "pincode": listing.pincode,
            "canonical_url": listing.canonical_url,
            "product_title": listing.product_title,
            "variant_title": listing.variant_title,
            "package_quantity": listing.package_quantity,
            "currency": listing.currency,
            "last_price_paise": listing.last_price_paise,
            "last_mrp_paise": listing.last_mrp_paise,
            "last_available": listing.last_available,
            "is_monitored": True,
        }
        res = self.client.table("canonical_listings").insert(payload).execute()
        return CanonicalListing(**res.data[0])

    async def get_listing_by_id(self, listing_id: int) -> Optional[CanonicalListing]:
        res = self.client.table("canonical_listings").select("*").eq("id", listing_id).execute()
        return CanonicalListing(**res.data[0]) if res.data else None

    async def claim_due_listings(
        self,
        worker_id: str,
        max_tier: int,
        min_tier: int = 1,
        batch_size: int = 25,
        lease_seconds: int = 300,
    ) -> List[CanonicalListing]:
        params = {
            "p_worker_id": worker_id,
            "p_max_tier": max_tier,
            "p_min_tier": min_tier,
            "p_batch_size": batch_size,
            "p_lease_seconds": lease_seconds,
        }
        res = self.client.rpc("claim_due_listings", params).execute()
        return [CanonicalListing(**row) for row in res.data]

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
        payload = {
            "last_price_paise": last_price_paise,
            "last_mrp_paise": last_mrp_paise,
            "last_available": last_available,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "next_check_at": next_check_at.isoformat(),
            "locked_until": None,
            "lock_owner": None,
            "consecutive_failures": consecutive_failures,
            "last_error_code": error_code,
            "last_error_message": error_message,
        }
        if canonical_url:
            payload["canonical_url"] = canonical_url
        self.client.table("canonical_listings").update(payload).eq("id", listing_id).execute()

    async def record_observation(self, observation: PriceObservation) -> None:
        payload = {
            "listing_id": observation.listing_id,
            "price_paise": observation.price_paise,
            "mrp_paise": observation.mrp_paise,
            "available": observation.available,
            "seller_name": observation.seller_name,
            "extraction_method": observation.extraction_method,
            "is_verified": observation.is_verified,
        }
        self.client.table("price_observations").insert(payload).execute()

    async def get_price_observations(
        self, listing_id: int, limit: int = 50
    ) -> List[PriceObservation]:
        res = (
            self.client.table("price_observations")
            .select("*")
            .eq("listing_id", listing_id)
            .order("observed_at", desc=False)
            .limit(limit)
            .execute()
        )
        return [PriceObservation(**row) for row in res.data]

    async def get_active_listings_by_provider(
        self, provider_code: str
    ) -> List[CanonicalListing]:
        res = (
            self.client.table("canonical_listings")
            .select("*")
            .eq("provider_code", provider_code)
            .eq("is_monitored", True)
            .execute()
        )
        return [CanonicalListing(**row) for row in res.data]

    # --- Subscription Repo ---
    async def create_or_update_subscription(self, sub: Subscription) -> Subscription:
        payload = {
            "telegram_id": sub.telegram_id,
            "listing_id": sub.listing_id,
            "target_price_paise": sub.target_price_paise,
            "is_active": True,
            "alert_rearmed": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = self.client.table("subscriptions").upsert(payload, on_conflict="telegram_id,listing_id").execute()
        return Subscription(**res.data[0])

    async def get_user_subscriptions(
        self, telegram_id: int, active_only: bool = True
    ) -> List[Tuple[Subscription, CanonicalListing]]:
        query = (
            self.client.table("subscriptions")
            .select("*, canonical_listings(*)")
            .eq("telegram_id", telegram_id)
        )
        if active_only:
            query = query.eq("is_active", True)

        res = query.execute()
        results: List[Tuple[Subscription, CanonicalListing]] = []
        for row in res.data:
            listing_data = row.pop("canonical_listings", None)
            if listing_data:
                sub = Subscription(**row)
                listing = CanonicalListing(**listing_data)
                results.append((sub, listing))
        return results

    async def deactivate_subscription(self, telegram_id: int, listing_id: int) -> bool:
        res = (
            self.client.table("subscriptions")
            .update({"is_active": False})
            .eq("telegram_id", telegram_id)
            .eq("listing_id", listing_id)
            .execute()
        )
        return bool(res.data)

    async def get_active_subscriptions_for_listing(self, listing_id: int) -> List[Subscription]:
        res = (
            self.client.table("subscriptions")
            .select("*")
            .eq("listing_id", listing_id)
            .eq("is_active", True)
            .execute()
        )
        return [Subscription(**row) for row in res.data]

    async def update_alert_state(
        self,
        subscription_id: int,
        last_alerted_price_paise: Optional[int],
        alert_rearmed: bool,
    ) -> None:
        payload = {
            "last_alerted_price_paise": last_alerted_price_paise,
            "last_alerted_at": datetime.now(timezone.utc).isoformat(),
            "alert_rearmed": alert_rearmed,
        }
        self.client.table("subscriptions").update(payload).eq("id", subscription_id).execute()

    async def log_notification(self, notif: NotificationLog) -> Optional[int]:
        payload = {
            "subscription_id": notif.subscription_id,
            "observation_id": notif.observation_id,
            "alert_type": notif.alert_type.value,
            "price_paise": notif.price_paise,
            "idempotency_key": notif.idempotency_key,
            "status": notif.status.value,
        }
        try:
            res = self.client.table("notification_log").insert(payload).execute()
            if res.data:
                return res.data[0]["id"]
            return None
        except Exception as exc:
            # Duplicate key violation on idempotency_key
            logger.info("Notification deduplicated via idempotency key in DB", key=notif.idempotency_key)
            return None
