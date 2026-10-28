"""Tests for vanishing command messages and verified bot menu commands."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.bot.commands_menu import DEFAULT_BOT_COMMANDS
from pricewatch.bot.handlers.commands import start_handler, untrack_handler
from pricewatch.domain.models import CanonicalListing, Subscription, User
from pricewatch.repositories.memory_repo import MemoryRepository
from pricewatch.services.tracker_service import TrackerService


@pytest.fixture
def mock_tracker_service():
    repo = MemoryRepository()
    return TrackerService(listing_repo=repo, subscription_repo=repo, user_repo=repo)


@pytest.mark.asyncio
async def test_start_untrack_deeplink_deletes_incoming_message(mock_tracker_service):
    """Verify that clicking [Untrack] sends /start untrack_<sku> which vanishes immediately."""
    # Seed a listing and subscription
    listing = CanonicalListing(
        id=42,
        provider_code="amul",
        external_product_id="SKU_BUTTERMILK",
        external_variant_id="SKU_BUTTERMILK",
        canonical_url="https://shop.amul.com/en/product/buttermilk",
        product_title="Amul High Protein Buttermilk",
    )
    saved_listing = await mock_tracker_service.listing_repo.get_or_create_listing(listing)
    await mock_tracker_service.sub_repo.create_or_update_subscription(
        Subscription(telegram_id=999, listing_id=saved_listing.id, target_price_paise=79900)
    )

    # Prepare Update and Context
    update = MagicMock()
    update.effective_user.id = 999
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.effective_message.delete = AsyncMock()
    update.effective_chat.send_message = AsyncMock()

    context = MagicMock()
    context.bot_data = {"tracker_service": mock_tracker_service}
    context.args = ["untrack_SKU_BUTTERMILK"]

    await start_handler(update, context)

    # 1. Incoming command message MUST be deleted so it vanishes
    update.effective_message.delete.assert_called_once()

    # 2. Response message must be delivered to the chat cleanly
    update.effective_chat.send_message.assert_called_once()
    sent_text = update.effective_chat.send_message.call_args[0][0]
    assert "Untracking product:" in sent_text
    assert "Amul High Protein Buttermilk" in sent_text

    # 3. Product is untracked
    subs = await mock_tracker_service.list_user_subscriptions(999)
    assert len(subs) == 0


@pytest.mark.asyncio
async def test_start_track_deeplink_deletes_incoming_message(mock_tracker_service):
    """Verify that clicking [Track] sends /start track_<sku> which vanishes immediately."""
    update = MagicMock()
    update.effective_user.id = 999
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.effective_message.delete = AsyncMock()
    update.effective_chat.send_message = AsyncMock()

    context = MagicMock()
    context.bot_data = {"tracker_service": mock_tracker_service}
    context.args = ["track_SKU_WHEY"]

    with patch("pricewatch.bot.handlers.commands.AmulProvider") as MockProv:
        instance = MockProv.return_value
        instance.fetch_quote = AsyncMock(
            return_value=MagicMock(raw_variant_title="Amul Whey Protein", price_paise=199900, available=True, inventory_quantity=50)
        )
        instance.fetch_category_products = AsyncMock(return_value=[{"sku": "SKU_WHEY", "name": "Amul Whey Protein", "alias": "whey"}])

        await start_handler(update, context)

    # Incoming message must vanish
    update.effective_message.delete.assert_called_once()
    update.effective_chat.send_message.assert_called_once()
    sent_text = update.effective_chat.send_message.call_args[0][0]
    assert "Tracking product:" in sent_text
    assert "Amul Whey Protein" in sent_text


@pytest.mark.asyncio
async def test_untrack_command_shorthand_deletes_incoming_message(mock_tracker_service):
    """Verify that tapping /untrack_42 vanishes immediately."""
    listing = CanonicalListing(
        id=77,
        provider_code="amul",
        external_product_id="SKU_LASSI",
        external_variant_id="SKU_LASSI",
        canonical_url="https://shop.amul.com/en/product/lassi",
        product_title="Amul Protein Lassi",
    )
    saved_listing = await mock_tracker_service.listing_repo.get_or_create_listing(listing)
    await mock_tracker_service.sub_repo.create_or_update_subscription(
        Subscription(telegram_id=999, listing_id=saved_listing.id, target_price_paise=2500)
    )

    update = MagicMock()
    update.effective_user.id = 999
    update.effective_message.text = f"/untrack_{saved_listing.id}"
    update.effective_message.delete = AsyncMock()
    update.effective_chat.send_message = AsyncMock()

    context = MagicMock()
    context.bot_data = {"tracker_service": mock_tracker_service}
    context.args = []

    await untrack_handler(update, context)

    # Incoming /untrack_77 message must be deleted
    update.effective_message.delete.assert_called_once()
    update.effective_chat.send_message.assert_called_once()
    sent_text = update.effective_chat.send_message.call_args[0][0]
    assert "Untracking product: Amul Protein Lassi" in sent_text

    subs = await mock_tracker_service.list_user_subscriptions(999)
    assert len(subs) == 0


def test_menu_commands_only_contain_working_commands():
    """Verify that all commands in DEFAULT_BOT_COMMANDS are valid and non-working commands are excluded."""
    commands = [c.command for c in DEFAULT_BOT_COMMANDS]
    # Usable working commands must be present
    for expected in ["start", "help", "products", "tracked", "trackall", "repeat", "settings", "pincode", "setpincode", "favourites", "search", "untrack", "track", "count", "analytics", "history", "map", "status", "support"]:
        assert expected in commands, f"Command {expected} missing from bot menu"

    # Non-working or unconfigured commands must NOT be present in menu
    assert "autoorder" not in commands
