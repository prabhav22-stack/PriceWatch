"""Unit tests for stepwise conversational onboarding and callback query dispatcher."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram import Update, User as TgUser, Message, Chat, CallbackQuery

from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import (
    amul_command_handler,
    history_command_handler,
    plain_text_handler,
)
from pricewatch.domain.models import CanonicalListing, PriceObservation, Subscription
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.tracker_service import TrackerService


@pytest.fixture
def memory_service():
    repo = MemoryRepository()
    return TrackerService(listing_repo=repo, subscription_repo=repo, user_repo=repo)


@pytest.mark.asyncio
async def test_plain_text_handler_with_custom_price(memory_service):
    # Setup listing
    listing = CanonicalListing(
        provider_code="amazon",
        provider_tier=1,
        external_product_id="B0123",
        external_variant_id="B0123",
        pincode="110001",
        canonical_url="https://amazon.in/dp/B0123",
        product_title="Whey Protein",
        variant_title="Default",
        currency="INR",
        last_price_paise=250000,
        is_monitored=True,
    )
    saved = await memory_service.listing_repo.get_or_create_listing(listing)

    # Mock Telegram Update & Context
    update = MagicMock(spec=Update)
    user = TgUser(id=12345, first_name="Prabhav", is_bot=False)
    chat = Chat(id=12345, type="private")
    message = MagicMock(spec=Message)
    message.text = "2199"
    message.reply_html = AsyncMock()

    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message

    context = MagicMock()
    context.bot_data = {"tracker_service": memory_service}
    context.user_data = {"awaiting_custom_price": saved.id}

    await plain_text_handler(update, context)

    # Context state cleared
    assert "awaiting_custom_price" not in context.user_data
    # Replied with confirmation
    message.reply_html.assert_called_once()
    reply_text = message.reply_html.call_args[0][0]
    assert "Now Tracking Product" in reply_text
    assert "₹2,199" in reply_text

    # Subscription created
    subs = await memory_service.sub_repo.get_user_subscriptions(12345)
    assert len(subs) == 1
    assert subs[0][0].target_price_paise == 219900


@pytest.mark.asyncio
async def test_callback_query_dispatcher_target_pills(memory_service):
    listing = CanonicalListing(
        provider_code="amazon",
        provider_tier=1,
        external_product_id="B0999",
        external_variant_id="B0999",
        pincode="110001",
        canonical_url="https://amazon.in/dp/B0999",
        product_title="Isolate Whey",
        variant_title="Default",
        currency="INR",
        last_price_paise=300000,
        is_monitored=True,
    )
    saved = await memory_service.listing_repo.get_or_create_listing(listing)

    update = MagicMock(spec=Update)
    query = MagicMock(spec=CallbackQuery)
    query.data = f"tgt:{saved.id}:270000"
    query.from_user = TgUser(id=99999, first_name="Alice", is_bot=False)
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query

    context = MagicMock()
    context.bot_data = {"tracker_service": memory_service}
    context.user_data = {"awaiting_custom_price": saved.id}

    await callback_query_dispatcher(update, context)

    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    reply_text = query.edit_message_text.call_args[0][0]
    assert "Now Tracking Product" in reply_text
    assert "₹2,700" in reply_text

    # Verify subscription in repo
    subs = await memory_service.sub_repo.get_user_subscriptions(99999)
    assert len(subs) == 1
    assert subs[0][0].target_price_paise == 270000


@pytest.mark.asyncio
async def test_amul_command_handler(memory_service):
    update = MagicMock(spec=Update)
    user = TgUser(id=555, first_name="Bob", is_bot=False)
    chat = Chat(id=555, type="private")
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message

    context = MagicMock()
    context.bot_data = {"tracker_service": memory_service}

    await amul_command_handler(update, context)

    message.reply_html.assert_called_once()
    text = message.reply_html.call_args[0][0]
    assert "Amul Products" in text
    assert "Select a category to view products" in text
    kb = message.reply_html.call_args[1]["reply_markup"]
    assert kb is not None
