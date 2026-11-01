"""Async Caching Layer with Stampede Protection and Circuit Breakers using Cashews."""

import os
from typing import Optional
from cashews import cache

from pricewatch.logging_setup import get_logger

logger = get_logger("core.cache")

# Initialize cashews cache
# Default to high-performance in-memory cache, or Redis if REDIS_URL is configured
redis_url: Optional[str] = os.getenv("REDIS_URL")
if redis_url:
    try:
        cache.setup(redis_url)
        logger.info("Cashews cache initialized with Redis backend", url=redis_url)
    except Exception as exc:
        logger.warning("Failed to initialize Redis backend for Cashews, falling back to memory", error=str(exc))
        cache.setup("mem://")
else:
    cache.setup("mem://")
    logger.info("Cashews cache initialized with in-memory backend")

__all__ = ["cache"]
