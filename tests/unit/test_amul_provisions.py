"""Unit tests for the 5 implemented Amul provisions:
1. Search across products
2. Favourites list & toggling
3. Warehouse analytics & product counts
4. Settings & notification limits
5. Headless Auto-Order service
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.bot.formatters import (
    format_amul_analytics,
    format_amul_favourites_messages,
    format_amul_product_count,
    format_amul_search_messages,
    format_auto_order_overview,
    format_settings_menu,
)
from pricewatch.domain.models import User
from pricewatch.providers.amul import AmulProvider
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.amul_auto_order import AmulAutoOrderService
from pricewatch.services.tracker_service import TrackerService


@pytest.fixture
def memory_tracker_service():
    repo = MemoryRepository()
    return TrackerService(listing_repo=repo, subscription_repo=repo, user_repo=repo)


@pytest.mark.asyncio
async def test_search_products_filter():
    provider = AmulProvider()
    mock_products = [
        {"sku": "WP_BLUEBERRY_30", "name": "Amul High Protein Blueberry Shake", "alias": "amul-blueberry", "available": True, "inventory_quantity": 10},
        {"sku": "WP_CHOCOLATE_30", "name": "Amul High Protein Chocolate Shake", "alias": "amul-chocolate", "available": False, "inventory_quantity": 0},
    ]

    with patch.object(provider, "fetch_category_products", new=AsyncMock(return_value=mock_products)):
        results = await provider.search_products("blueberry", pincode="842002", categories=["protein"])
        assert len(results) == 1
        assert results[0]["sku"] == "WP_BLUEBERRY_30"

        empty_results = await provider.search_products("nonexistent_item_xyz", pincode="842002", categories=["protein"])
        assert len(empty_results) == 0


@pytest.mark.asyncio
async def test_favourites_toggle_and_retrieval(memory_tracker_service):
    user_id = 999888
    user = await memory_tracker_service.get_or_register_user(user_id)
    assert user.favourite_skus == []

    # 1. Add favourite
    added = await memory_tracker_service.toggle_user_favourite(user_id, "WP_BLUEBERRY_30")
    assert added is True
    updated_user = await memory_tracker_service.get_or_register_user(user_id)
    assert "WP_BLUEBERRY_30" in updated_user.favourite_skus

    # 2. Remove favourite
    removed = await memory_tracker_service.toggle_user_favourite(user_id, "WP_BLUEBERRY_30")
    assert removed is False
    updated_user2 = await memory_tracker_service.get_or_register_user(user_id)
    assert "WP_BLUEBERRY_30" not in updated_user2.favourite_skus


def test_analytics_and_product_count_formatters():
    mock_products = [
        {"sku": "SKU1", "name": "Buttermilk", "available": True, "inventory_quantity": 50},
        {"sku": "SKU2", "name": "Whey Protein", "available": False, "inventory_quantity": 0},
    ]

    analytics_text = format_amul_analytics(
        substore="bihar",
        pincode="842002",
        products=mock_products,
        user_tracked_count=1,
    )
    assert "Amul Warehouse Analytics" in analytics_text
    assert "842002" in analytics_text
    assert "Currently In Stock: <b>1</b> (50% 🟢)" in analytics_text

    count_text = format_amul_product_count(mock_products)
    assert "Amul Available Product Counts" in count_text
    assert "Buttermilk" in count_text
    assert "50 units" in count_text


def test_settings_menu_and_user_model():
    user = User(
        telegram_id=12345,
        default_pincode="842002",
        tracking_style="always",
        max_notify_count=3,
        auto_order_enabled=True,
        auto_order_phone="9876543210",
    )
    settings_text = format_settings_menu(user)
    assert "Always 🔄" in settings_text
    assert "3" in settings_text
    assert "Enabled 🟢" in settings_text
    assert "9876543210" in settings_text


@pytest.mark.asyncio
async def test_auto_order_service_otp_validation():
    service = AmulAutoOrderService()

    # Invalid phone check
    res_phone = await service.request_otp("1234")
    assert res_phone["success"] is False
    assert "10-digit" in res_phone["message"]

    # Invalid OTP check
    res_otp = await service.verify_otp("9876543210", "12")
    assert res_otp["success"] is False
    assert "6-digit" in res_otp["message"]

    user = User(telegram_id=123, auto_order_skus=["BTMCP11_30"])
    overview_text = format_auto_order_overview(user)
    assert "Amul Headless Auto-Order Engine" in overview_text
    assert "BTMCP11_30" in overview_text
