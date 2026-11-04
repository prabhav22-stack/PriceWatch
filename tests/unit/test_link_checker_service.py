"""Unit tests for asynchronous link health checker and dead-link quarantine."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pricewatch.services.link_checker_service import LinkHealthChecker


@pytest.mark.asyncio
async def test_link_checker_structural_validation():
    checker = LinkHealthChecker()
    # Bad search URLs must fail immediately without HTTP call
    is_ok, reason = await checker.verify_url_live("https://www.amazon.in/s?k=whey")
    assert is_ok is False
    assert "Structural" in reason

    is_ok, reason = await checker.verify_url_live("https://www.flipkart.com/search?q=whey")
    assert is_ok is False


@pytest.mark.asyncio
async def test_link_checker_quarantines_404():
    checker = LinkHealthChecker()
    bad_url = "https://www.amazon.in/dp/B000000000"

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.url = bad_url

    with patch("pricewatch.services.link_checker_service.http_client.get", new=AsyncMock(return_value=mock_resp)):
        is_ok, reason = await checker.verify_url_live(bad_url)
        assert is_ok is False
        assert "404" in reason
        # Second call should be quarantined immediately
        assert checker.is_quarantined(bad_url) is True


@pytest.mark.asyncio
async def test_link_checker_filter_live_deals():
    checker = LinkHealthChecker()
    deals = [
        {"title": "Good Deal", "url": "https://www.amazon.in/dp/B07X2QKVXH"},
        {"title": "Bad Search Link", "url": "https://www.amazon.in/s?k=whey"},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://www.amazon.in/dp/B07X2QKVXH"

    with patch("pricewatch.services.link_checker_service.http_client.get", new=AsyncMock(return_value=mock_resp)):
        live = await checker.filter_live_deals(deals)
        assert len(live) == 1
        assert live[0]["title"] == "Good Deal"
