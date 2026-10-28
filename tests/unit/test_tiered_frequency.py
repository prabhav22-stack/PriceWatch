"""Unit tests for Strategy C: Tiered Frequency by Store Provider."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram import Message, Update, User as TgUser

from pricewatch.config import get_provider_check_interval, settings
from pricewatch.bot.handlers.commands import check_command_handler, status_handler
from pricewatch.domain.models import CanonicalListing, PriceQuote, Subscription
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.tracker_service import TrackerService


def test_get_provider_check_interval():
    # Tier 1: Amul StoreHippo REST API -> 30s
    assert get_provider_check_interval("amul") == timedelta(seconds=settings.AMUL_CHECK_INTERVAL_SECONDS)
    assert get_provider_check_interval("amul").total_seconds() == 30.0

    # Tier 2: Shopify stores -> 3 minutes
    assert get_provider_check_interval("shopify:nakpro.com") == timedelta(minutes=settings.SHOPIFY_CHECK_INTERVAL_MINUTES)
    assert get_provider_check_interval("shopify:nakpro.com").total_seconds() == 180.0
    assert get_provider_check_interval("shopify:muscleblaze.com") == timedelta(minutes=settings.SHOPIFY_CHECK_INTERVAL_MINUTES)

    # Tier 3: Marketplaces -> 15 minutes
    assert get_provider_check_interval("amazon") == timedelta(minutes=settings.MARKETPLACE_CHECK_INTERVAL_MINUTES)
    assert get_provider_check_interval("amazon_fresh") == timedelta(minutes=settings.MARKETPLACE_CHECK_INTERVAL_MINUTES)
    assert get_provider_check_interval("flipkart") == timedelta(minutes=settings.MARKETPLACE_CHECK_INTERVAL_MINUTES)

    # Fallback
    assert get_provider_check_interval("unknown") == timedelta(minutes=settings.DEFAULT_CHECK_INTERVAL_MINUTES)


@pytest.mark.asyncio
async def test_status_handler_displays_tiered_frequencies():
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()
    update.effective_message = message

    context = MagicMock()

    await status_handler(update, context)
    message.reply_html.assert_called_once()
    sent_text = message.reply_html.call_args[0][0]

    assert "Amul Shop:" in sent_text
    assert "30s" in sent_text
    assert "Shopify Stores" in sent_text
    assert "3 minutes" in sent_text
    assert "Amazon" in sent_text
    assert "15 minutes" in sent_text
    assert "/check" in sent_text


@pytest.mark.asyncio
async def test_check_command_handler_empty():
    repo = MemoryRepository()
    service = TrackerService(listing_repo=repo, subscription_repo=repo, user_repo=repo)

    update = MagicMock(spec=Update)
    user = TgUser(id=123, first_name="Prabhav", is_bot=False)
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()
    update.effective_user = user
    update.effective_message = message

    context = MagicMock()
    context.bot_data = {"tracker_service": service}

    await check_command_handler(update, context)
    message.reply_html.assert_called_once()
    sent_text = message.reply_html.call_args[0][0]
    assert "You have no active tracked items to check" in sent_text
