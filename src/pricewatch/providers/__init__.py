"""E-commerce store scrapers and provider registry."""

from pricewatch.providers.base import BaseProvider, ProviderRegistry
from pricewatch.providers.shopify import ShopifyProvider
from pricewatch.providers.amazon_fresh import AmazonFreshProvider
from pricewatch.providers.generic import GenericProvider

__all__ = [
    "BaseProvider",
    "ProviderRegistry",
    "ShopifyProvider",
    "AmazonFreshProvider",
    "GenericProvider",
]
