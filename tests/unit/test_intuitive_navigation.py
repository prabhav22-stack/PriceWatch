"""Unit tests for the new intuitive navigation keyboards and callback handlers."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram import CallbackQuery, Chat, Message, Update, User as TgUser

from pricewatch.bot.handlers.callbacks import callback_query_dispatcher
from pricewatch.bot.handlers.commands import (
    pincode_handler,
    repeat_command_handler,
    start_handler,
)
from pricewatch.bot.keyboards import (
    build_action_nav_keyboard,
    build_amul_category_keyboard,
    build_category_navigation_keyboard,
    build_pincode_keyboard,
    build_repeat_keyboard,
    build_search_suggestions_keyboard,
    build_welcome_keyboard,
)
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.tracker_service import TrackerService


@pytest.fixture
def memory_service():
    repo = MemoryRepository()
    return TrackerService(listing_repo=repo, subscription_repo=repo, user_repo=repo)


def test_keyboards_structure():
    # Welcome keyboard
    kb_w = build_welcome_keyboard()
    assert any("Browse Amul" in btn.text for row in kb_w.inline_keyboard for btn in row)
    assert any("Favourites" in btn.text for row in kb_w.inline_keyboard for btn in row)

    # Category menu with navigation
    kb_cat = build_amul_category_keyboard(pincode="842002")
    assert any("Protein" in btn.text for row in kb_cat.inline_keyboard for btn in row)
    assert any("PIN: 842002" in btn.text for row in kb_cat.inline_keyboard for btn in row)

    # Category navigation keyboard
    kb_nav = build_category_navigation_keyboard("protein")
    assert any("Back to Categories" in btn.text for row in kb_nav.inline_keyboard for btn in row)

    # Pincode hub keyboard
    kb_pin = build_pincode_keyboard("842002")
    assert any("Muzaffarpur" in btn.text for row in kb_pin.inline_keyboard for btn in row)
    assert any("Delhi" in btn.text for row in kb_pin.inline_keyboard for btn in row)

    # Repeat keyboard
    kb_rep = build_repeat_keyboard(0)
    assert any("Until OOS" in btn.text for row in kb_rep.inline_keyboard for btn in row)

    # Search suggestions keyboard
    kb_search = build_search_suggestions_keyboard()
    assert any("Blueberry" in btn.text for row in kb_search.inline_keyboard for btn in row)
    assert any("Whey" in btn.text for row in kb_search.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_start_command_attaches_welcome_keyboard(memory_service):
    update = MagicMock(spec=Update)
    user = TgUser(id=999, first_name="Prabhav", is_bot=False)
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()

    update.effective_user = user
    update.effective_message = message

    context = MagicMock()
    context.args = []
    context.bot_data = {"tracker_service": memory_service}

    await start_handler(update, context)
    message.reply_html.assert_called_once()
    _, kwargs = message.reply_html.call_args
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"]
    assert any("Browse Amul" in btn.text for row in kb.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_pincode_command_attaches_hub_keyboard(memory_service):
    update = MagicMock(spec=Update)
    user = TgUser(id=999, first_name="Prabhav", is_bot=False)
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()

    update.effective_user = user
    update.effective_message = message

    context = MagicMock()
    context.args = []
    context.bot_data = {"tracker_service": memory_service}

    await pincode_handler(update, context)
    message.reply_html.assert_called_once()
    _, kwargs = message.reply_html.call_args
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"]
    assert any("Muzaffarpur" in btn.text for row in kb.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_repeat_command_attaches_keypad(memory_service):
    update = MagicMock(spec=Update)
    user = TgUser(id=999, first_name="Prabhav", is_bot=False)
    message = MagicMock(spec=Message)
    message.reply_html = AsyncMock()

    update.effective_user = user
    update.effective_message = message

    context = MagicMock()
    context.args = []
    context.bot_data = {"tracker_service": memory_service}

    await repeat_command_handler(update, context)
    message.reply_html.assert_called_once()
    _, kwargs = message.reply_html.call_args
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"]
    assert any("Until OOS" in btn.text for row in kb.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_nav_callbacks_dispatch(memory_service):
    # Test nav:search
    update = MagicMock(spec=Update)
    user = TgUser(id=999, first_name="Prabhav", is_bot=False)
    query = MagicMock(spec=CallbackQuery)
    query.from_user = user
    query.data = "nav:search"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.bot_data = {"tracker_service": memory_service}

    await callback_query_dispatcher(update, context)
    query.edit_message_text.assert_called_once()
    _, kwargs = query.edit_message_text.call_args
    assert "reply_markup" in kwargs

    # Test set_pin:110001
    query.data = "set_pin:110001"
    query.edit_message_text.reset_mock()
    await callback_query_dispatcher(update, context)
    db_user = await memory_service.get_or_register_user(999)
    assert db_user.default_pincode == "110001"
    query.edit_message_text.assert_called_once()
