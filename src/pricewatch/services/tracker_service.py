"""Tracker service managing product onboarding, variant disambiguation, and user limits."""

from typing import Any, List, Optional, Tuple

from pricewatch.config import settings
from pricewatch.domain.exceptions import (
    PriceWatchError,
    VariantAmbiguousError,
)
from pricewatch.domain.models import (
    CanonicalListing,
    PriceObservation,
    ResolutionResult,
    Subscription,
    User,
)
from pricewatch.providers.base import ProviderRegistry
from pricewatch.repositories.base import (
    BaseListingRepo,
    BaseSubscriptionRepo,
    BaseUserRepo,
)


class TrackerService:
    """Coordinates product URL onboarding, variant selection, and subscription management."""

    def __init__(
        self,
        listing_repo: BaseListingRepo,
        subscription_repo: BaseSubscriptionRepo,
        user_repo: BaseUserRepo,
    ):
        self.listing_repo = listing_repo
        self.sub_repo = subscription_repo
        self.user_repo = user_repo

    async def get_or_register_user(
        self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None
    ) -> User:
        return await self.user_repo.get_or_create_user(telegram_id, username, first_name)

    async def set_user_pincode(self, telegram_id: int, pincode: str) -> None:
        await self.user_repo.update_default_pincode(telegram_id, pincode)

    async def list_user_subscriptions(
        self, telegram_id: int
    ) -> List[Tuple[Subscription, CanonicalListing]]:
        return await self.sub_repo.get_user_subscriptions(telegram_id, active_only=True)

    async def get_listing(self, listing_id: int) -> Optional[CanonicalListing]:
        """Fetch canonical listing by ID."""
        return await self.listing_repo.get_listing_by_id(listing_id)

    async def get_price_history(self, listing_id: int, limit: int = 50) -> List[PriceObservation]:
        """Fetch price observations for a listing."""
        return await self.listing_repo.get_price_observations(listing_id, limit=limit)

    async def resolve_and_preview_url(
        self,
        telegram_id: int,
        url: str,
        pincode: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> CanonicalListing:
        """
        Step 1 of stepwise onboarding:
        Inspects product URL, creates or retrieves canonical listing, and returns it for user preview.
        """
        user = await self.user_repo.get_or_create_user(telegram_id, username, first_name)
        effective_pincode = pincode or user.default_pincode or ""
        provider = ProviderRegistry.get_provider_for_url(url)

        resolution = await provider.resolve_url(url, pincode=effective_pincode)

        pinned_variant_id = resolution.pinned_variant_id or "default"
        matched_opt = next(
            (v for v in resolution.variants if v.external_variant_id == pinned_variant_id),
            resolution.variants[0] if resolution.variants else None,
        )

        variant_title = matched_opt.variant_title if matched_opt else "Default"
        canonical_url = matched_opt.canonical_url if matched_opt else url
        last_price = matched_opt.price_paise if matched_opt else None
        last_mrp = matched_opt.mrp_paise if matched_opt else None
        last_avail = matched_opt.available if matched_opt else True
        inv_qty = matched_opt.inventory_quantity if matched_opt else None

        listing_to_create = CanonicalListing(
            provider_code=resolution.provider_code,
            provider_tier=int(resolution.provider_tier),
            external_product_id=resolution.external_product_id,
            external_variant_id=pinned_variant_id,
            pincode=effective_pincode,
            canonical_url=canonical_url,
            product_title=resolution.product_title,
            variant_title=variant_title,
            currency="INR",
            last_price_paise=last_price,
            last_mrp_paise=last_mrp,
            last_available=last_avail,
            inventory_quantity=inv_qty,
            is_monitored=True,
        )

        return await self.listing_repo.get_or_create_listing(listing_to_create)

    async def create_subscription_for_listing(
        self,
        telegram_id: int,
        listing_id: int,
        target_price_paise: int,
        notify_on_restock: bool = False,
    ) -> Tuple[CanonicalListing, Subscription]:
        """
        Step 2 of stepwise onboarding:
        Subscribes user to a listing at their chosen target price.
        """
        listing = await self.listing_repo.get_listing_by_id(listing_id)
        if not listing:
            raise PriceWatchError(f"Listing {listing_id} not found.")

        subscription_to_create = Subscription(
            telegram_id=telegram_id,
            listing_id=listing_id,
            target_price_paise=target_price_paise,
            notify_on_restock=notify_on_restock,
            is_active=True,
            alert_rearmed=True,
        )

        saved_sub = await self.sub_repo.create_or_update_subscription(subscription_to_create)
        return listing, saved_sub

    async def untrack_product(self, telegram_id: int, listing_id: int) -> bool:
        return await self.sub_repo.deactivate_subscription(telegram_id, listing_id)

    async def track_url(
        self,
        telegram_id: int,
        url: str,
        target_price_paise: int,
        pincode: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> Tuple[CanonicalListing, Subscription]:
        """
        Onboard a product URL for tracking.
        If URL has multiple variants and no pinned variant in URL, raises VariantAmbiguousError.
        """
        user = await self.user_repo.get_or_create_user(telegram_id, username, first_name)

        # Check user item limit
        existing_subs = await self.sub_repo.get_user_subscriptions(telegram_id, active_only=True)
        if len(existing_subs) >= settings.MAX_ITEMS_PER_USER:
            raise PriceWatchError(
                f"You have reached the maximum tracking limit ({settings.MAX_ITEMS_PER_USER} products)."
            )

        effective_pincode = pincode or user.default_pincode or ""
        provider = ProviderRegistry.get_provider_for_url(url)

        # resolve_url may raise VariantAmbiguousError
        resolution = await provider.resolve_url(url, pincode=effective_pincode)

        pinned_variant_id = resolution.pinned_variant_id or "default"
        # Find matched variant option
        matched_opt = next(
            (v for v in resolution.variants if v.external_variant_id == pinned_variant_id),
            resolution.variants[0] if resolution.variants else None,
        )

        variant_title = matched_opt.variant_title if matched_opt else "Default"
        canonical_url = matched_opt.canonical_url if matched_opt else url
        last_price = matched_opt.price_paise if matched_opt else None
        last_mrp = matched_opt.mrp_paise if matched_opt else None
        last_avail = matched_opt.available if matched_opt else True

        listing_to_create = CanonicalListing(
            provider_code=resolution.provider_code,
            provider_tier=int(resolution.provider_tier),
            external_product_id=resolution.external_product_id,
            external_variant_id=pinned_variant_id,
            pincode=effective_pincode,
            canonical_url=canonical_url,
            product_title=resolution.product_title,
            variant_title=variant_title,
            currency="INR",
            last_price_paise=last_price,
            last_mrp_paise=last_mrp,
            last_available=last_avail,
            is_monitored=True,
        )

        saved_listing = await self.listing_repo.get_or_create_listing(listing_to_create)

        subscription_to_create = Subscription(
            telegram_id=telegram_id,
            listing_id=saved_listing.id,
            target_price_paise=target_price_paise,
            is_active=True,
            alert_rearmed=True,
        )

        saved_sub = await self.sub_repo.create_or_update_subscription(subscription_to_create)
        return saved_listing, saved_sub

    async def track_pinned_variant(
        self,
        telegram_id: int,
        provider_code: str,
        external_product_id: str,
        variant_id: str,
        product_title: str,
        variant_title: str,
        canonical_url: str,
        target_price_paise: int,
        pincode: str = "",
        last_price_paise: Optional[int] = None,
        last_mrp_paise: Optional[int] = None,
        available: bool = True,
    ) -> Tuple[CanonicalListing, Subscription]:
        """Callback handler when user selects a specific variant from the inline keyboard."""
        listing = CanonicalListing(
            provider_code=provider_code,
            provider_tier=1,
            external_product_id=external_product_id,
            external_variant_id=variant_id,
            pincode=pincode,
            canonical_url=canonical_url,
            product_title=product_title,
            variant_title=variant_title,
            currency="INR",
            last_price_paise=last_price_paise,
            last_mrp_paise=last_mrp_paise,
            last_available=available,
            is_monitored=True,
        )

        saved_listing = await self.listing_repo.get_or_create_listing(listing)

        subscription = Subscription(
            telegram_id=telegram_id,
            listing_id=saved_listing.id,
            target_price_paise=target_price_paise,
            is_active=True,
            alert_rearmed=True,
        )

        saved_sub = await self.sub_repo.create_or_update_subscription(subscription)
        return saved_listing, saved_sub
