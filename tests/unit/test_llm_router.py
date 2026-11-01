"""Unit tests for Hybrid LLM Router (Groq + Gemini fallback)."""

import pytest
from unittest.mock import AsyncMock, patch
from pricewatch.services.llm_router import HybridLLMRouter


@pytest.mark.asyncio
async def test_llm_router_groq_normalization():
    """Verify router executes Groq normalization when available."""
    router = HybridLLMRouter()
    mock_data = {
        "brand": "Nakpro",
        "series": "Perform",
        "category": "whey",
        "weight_g": 1000,
        "flavor": "Chocolate",
        "clean_query": "Nakpro Perform Whey Protein 1kg Chocolate",
    }

    with patch.object(router, "_normalize_via_groq", new=AsyncMock(return_value=mock_data)):
        res = await router.normalize_user_query("nakpro choc whey 1k")
        assert res is not None
        assert res["clean_query"] == "Nakpro Perform Whey Protein 1kg Chocolate"


@pytest.mark.asyncio
async def test_llm_router_gemini_fallback():
    """Verify router falls back to Gemini if Groq fails or is unavailable."""
    router = HybridLLMRouter()
    mock_gemini_data = {
        "brand": "Nutrabay",
        "category": "shilajit",
        "clean_query": "Nutrabay Pure Shilajit Resin 20g",
    }

    # Groq fails, Gemini succeeds
    with patch.object(router, "_normalize_via_groq", new=AsyncMock(return_value=None)):
        with patch("pricewatch.services.llm_router.gemini_service.normalize_user_query", new=AsyncMock(return_value=mock_gemini_data)):
            res = await router.normalize_user_query("nutrabay shilajit")
            assert res is not None
            assert res["clean_query"] == "Nutrabay Pure Shilajit Resin 20g"
