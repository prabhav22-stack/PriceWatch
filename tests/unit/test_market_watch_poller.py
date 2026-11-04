"""Unit tests for background Market Watch poller and brand crash alerts."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.bot.keyboards import build_settings_keyboard
from pricewatch.bot.formatters import format_settings_menu
from pricewatch.domain.models import User
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.market_watch_poller import (
    _build_alert_text,
    _fetch_deals_for_query,
    _is_cooled_down,
    _mark_alerted,
    _last_alerted,
    run_market_watch_poller,
    DISCOUNT_THRESHOLD_PCT,
)


def test_user_market_watch_enabled_default():
    u = User(telegram_id=123)
    assert u.market_watch_enabled is False


def test_format_settings_menu_reflects_market_watch():
    u_off = User(telegram_id=123, market_watch_enabled=False)
    text_off = format_settings_menu(u_off)
    assert "Market Watch:" in text_off
    assert "Off" in text_off

    u_on = User(telegram_id=123, market_watch_enabled=True)
    text_on = format_settings_menu(u_on)
    assert "Market Watch:" in text_on
    assert "Active" in text_on


def test_build_settings_keyboard_has_market_watch_button():
    u_off = User(telegram_id=123, market_watch_enabled=False)
    kb_off = build_settings_keyboard(u_off)
    buttons_off = [btn.text for row in kb_off.inline_keyboard for btn in row]
    assert any("Market Watch: OFF" in b for b in buttons_off)

    u_on = User(telegram_id=123, market_watch_enabled=True)
    kb_on = build_settings_keyboard(u_on)
    buttons_on = [btn.text for row in kb_on.inline_keyboard for btn in row]
    assert any("Market Watch: ON" in b for b in buttons_on)


def test_build_alert_text():
    deal = {
        "title": "Nakpro Gold Whey Concentrate",
        "price_inr": 1500.0,
        "mrp_inr": 2500.0,
        "discount_pct": 40.0,
        "store": "Nakpro Direct",
        "url": "https://nakpro.com/products/test",
    }
    msg = _build_alert_text(deal)
    assert "Market Watch Alert!" in msg
    assert "Nakpro Gold Whey Concentrate" in msg
    assert "40% OFF" in msg
    assert "https://nakpro.com/products/test" in msg


def test_cooldown_mechanism():
    user_id = 99999
    prod_key = "nakpro-deal-1"
    _last_alerted.clear()

    assert _is_cooled_down(user_id, prod_key) is True
    _mark_alerted(user_id, prod_key)
    assert _is_cooled_down(user_id, prod_key) is False


@pytest.mark.asyncio
async def test_fetch_deals_for_query_filters_low_discount():
    mock_results = [
        # Deal 1: 30% discount -> qualifies (>= 25%)
        {
            "title": "Nakpro Whey 1kg",
            "price": 140000,  # paise
            "mrp": 200000,    # paise -> 30% off
            "store": "Nakpro",
            "url": "https://nakpro.com/deal",
        },
        # Deal 2: 10% discount -> filtered out
        {
            "title": "Expensive Whey 1kg",
            "price": 180000,
            "mrp": 200000,
            "store": "Store",
            "url": "https://store.com/item",
        },
    ]

    with patch("pricewatch.services.market_watch_poller.query_all_stores", new=AsyncMock(return_value=mock_results)):
        deals = await _fetch_deals_for_query("nakpro whey")
        assert len(deals) == 1
        assert deals[0]["title"] == "Nakpro Whey 1kg"
        assert deals[0]["discount_pct"] == 30.0


@pytest.mark.asyncio
async def test_run_market_watch_poller_alerts_opted_in_user():
    repo = MemoryRepository()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    _last_alerted.clear()

    # User 1 has market_watch_enabled=True
    u1 = await repo.get_or_create_user(telegram_id=111)
    await repo.update_user_settings(111, market_watch_enabled=True)

    # User 2 has market_watch_enabled=False
    u2 = await repo.get_or_create_user(telegram_id=222)
    await repo.update_user_settings(222, market_watch_enabled=False)

    fake_deal = [{
        "title": "MuscleBlaze Biozyme Whey 1kg",
        "price": 199900,
        "mrp": 329900,  # ~39% discount
        "store": "Flipkart",
        "url": "https://flipkart.com/mb-biozyme",
    }]

    with patch("pricewatch.services.market_watch_poller.query_all_stores", new=AsyncMock(return_value=fake_deal)):
        poller_task = asyncio.create_task(run_market_watch_poller(repo=repo, bot=bot, interval_seconds=1))
        await asyncio.sleep(0.2)
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass

    # Bot should send message to User 1 only
    bot.send_message.assert_called()
    called_chats = [call.kwargs.get("chat_id") for call in bot.send_message.call_args_list]
    assert 111 in called_chats
    assert 222 not in called_chats
