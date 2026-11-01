"""Unit tests for Gemini Service query normalization and multimodal vision."""

import pytest
from unittest.mock import AsyncMock, patch
from pricewatch.services.gemini_service import GeminiService


@pytest.mark.asyncio
async def test_gemini_service_availability():
    """Verify GeminiService correctly detects API key availability."""
    svc = GeminiService()
    # is_available should be boolean
    assert isinstance(svc.is_available, bool)


@pytest.mark.asyncio
async def test_gemini_normalize_query_parsing():
    """Verify query normalization parses Gemini JSON output."""
    svc = GeminiService()
    svc.api_key = "test_key_long_enough_for_validation"
    mock_json = '{"brand": "Nakpro", "series": "Perform", "category": "whey", "weight_g": 1000, "flavor": "unflavoured", "clean_query": "Nakpro Perform 1kg Unflavoured"}'

    with patch.object(svc, "_call_gemini", new=AsyncMock(return_value=mock_json)):
        res = await svc.normalize_user_query("nakpro perform choc 1k")
        assert res is not None
        assert res["brand"] == "Nakpro"
        assert res["series"] == "Perform"
        assert res["clean_query"] == "Nakpro Perform 1kg Unflavoured"


@pytest.mark.asyncio
async def test_gemini_deal_verdict_generation():
    """Verify deal verdict string generation."""
    svc = GeminiService()
    svc.api_key = "test_key_long_enough_for_validation"
    mock_verdict = "Amazon offers the best price on Nakpro Perform with immediate stock."

    with patch.object(svc, "_call_gemini", new=AsyncMock(return_value=mock_verdict)):
        verdict = await svc.generate_quick_deal_verdict("Nakpro Perform 1kg", "Amazon", 2089, 110)
        assert verdict == mock_verdict
