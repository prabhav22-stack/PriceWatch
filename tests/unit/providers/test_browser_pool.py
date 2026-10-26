"""Unit tests for Playwright BrowserPool."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pricewatch.domain.exceptions import BotBlockedError
from pricewatch.providers.browser_pool import BrowserPool


@pytest.mark.asyncio
async def test_browser_pool_fetch_success():
    mock_page = AsyncMock()
    mock_page.title.return_value = "Amazon.in : Whey Protein"
    mock_page.content.return_value = "<html><body>Amazon Content</body></html>"
    mock_page.query_selector.return_value = None

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_p = AsyncMock()
    mock_p.chromium.launch.return_value = mock_browser

    with patch("pricewatch.providers.browser_pool.async_playwright") as mock_ap:
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_p
        mock_cm.__aexit__.return_value = None
        mock_ap.return_value = mock_cm

        html = await BrowserPool.fetch_amazon_fresh_page("https://www.amazon.in/dp/B079SZJJDR")
        assert "Amazon Content" in html
        mock_page.goto.assert_called_once()


@pytest.mark.asyncio
async def test_browser_pool_robot_check_raises_bot_blocked():
    mock_page = AsyncMock()
    mock_page.title.return_value = "Robot Check"

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_p = AsyncMock()
    mock_p.chromium.launch.return_value = mock_browser

    with patch("pricewatch.providers.browser_pool.async_playwright") as mock_ap:
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_p
        mock_cm.__aexit__.return_value = None
        mock_ap.return_value = mock_cm

        with pytest.raises(BotBlockedError):
            await BrowserPool.fetch_amazon_fresh_page("https://www.amazon.in/dp/B079SZJJDR")
