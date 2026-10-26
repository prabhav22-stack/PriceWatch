"""Base provider abstract class and provider registry."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type
from urllib.parse import urlparse

from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.models import PriceQuote, ResolutionResult


class BaseProvider(ABC):
    """Abstract protocol for all e-commerce store providers."""
    provider_code: str
    tier: ProviderTier

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str) -> bool:
        """Return True if this provider supports the given URL."""

    @abstractmethod
    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        """Inspect URL during /track onboarding; return available variants."""

    @abstractmethod
    async def fetch_quote(
        self,
        canonical_url: str,
        external_product_id: str,
        external_variant_id: str,
        pincode: str = "",
    ) -> PriceQuote:
        """Fetch current price/availability for a pinned canonical listing."""


class ProviderRegistry:
    """Registry for discovering and routing URLs to providers."""
    _providers: List[Type[BaseProvider]] = []
    _code_map: Dict[str, Type[BaseProvider]] = {}
    _fallback_provider: Optional[Type[BaseProvider]] = None

    @classmethod
    def register(cls, provider_cls: Type[BaseProvider]) -> Type[BaseProvider]:
        """Register a provider class."""
        if provider_cls not in cls._providers:
            cls._providers.append(provider_cls)
            if hasattr(provider_cls, "provider_code") and provider_cls.provider_code:
                cls._code_map[provider_cls.provider_code] = provider_cls
        return provider_cls

    @classmethod
    def set_fallback(cls, provider_cls: Type[BaseProvider]) -> None:
        """Set the generic fallback provider."""
        cls._fallback_provider = provider_cls

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._providers:
            import pricewatch.providers  # noqa: F401

    @classmethod
    def get_provider_for_url(cls, url: str) -> BaseProvider:
        """Find the matching provider instance for a URL, or return the fallback."""
        cls._ensure_loaded()
        for provider_cls in cls._providers:
            if provider_cls.can_handle(url):
                return provider_cls()
        if cls._fallback_provider:
            return cls._fallback_provider()
        raise ValueError(f"No provider found for URL: {url}")

    @classmethod
    def get_provider_by_code(cls, code: str) -> BaseProvider:
        """Retrieve a provider instance by its unique provider_code."""
        cls._ensure_loaded()
        if code in cls._code_map:
            return cls._code_map[code]()
        # If code starts with shopify:
        if code.startswith("shopify:"):
            from pricewatch.providers.shopify import ShopifyProvider
            return ShopifyProvider()
        if cls._fallback_provider:
            return cls._fallback_provider()
        raise ValueError(f"Unknown provider code: {code}")

    @classmethod
    def clear(cls) -> None:
        """Reset registry (primarily for tests)."""
        cls._providers.clear()
        cls._code_map.clear()
        cls._fallback_provider = None
