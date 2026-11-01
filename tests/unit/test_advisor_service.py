import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from telegram import Update
from pricewatch.bot.handlers.commands import plain_text_handler
from pricewatch.domain.models import ComparisonResult, StoreDeal
from pricewatch.services.advisor_service import (
    ChatIntent,
    ConversationalAdvisorService,
    advisor_service,
    is_trusted_brand,
)
from pricewatch.services.llm_router import HybridLLMRouter


def test_is_trusted_brand():
    assert is_trusted_brand("Nakpro Perform Whey") is True
    assert is_trusted_brand("AS-IT-IS Nutrition Whey 1kg") is True
    assert is_trusted_brand("Amul Protein Lassi") is True
    assert is_trusted_brand("Optimum Nutrition ON Gold Standard") is True
    assert is_trusted_brand("Kapiva Himalayan Shilajit Resin") is True

    # "on" word boundary test: Nutrition should NOT match "on" alone
    assert is_trusted_brand("Random Brand Nutrition Whey") is False


@pytest.mark.asyncio
async def test_parse_chat_intent_heuristics():
    svc = ConversationalAdvisorService()

    # Disable LLM to test heuristic fallback
    with patch.object(HybridLLMRouter, "has_groq", new_callable=PropertyMock, return_value=False), \
         patch.object(HybridLLMRouter, "has_gemini", new_callable=PropertyMock, return_value=False):
        # 1. Recommendation
        res1 = await svc.parse_chat_intent("top 5 shilajit under Rs 1000")
        assert res1.intent_type == "recommendation"
        assert res1.category == "shilajit"
        assert res1.max_budget_inr == 1000

        # 2. Comparison
        res2 = await svc.parse_chat_intent("Nakpro Perform 1kg unflavoured")
        assert res2.intent_type == "comparison"

        # 3. Greeting
        res3 = await svc.parse_chat_intent("hello")
        assert res3.intent_type == "general_chat"
        assert "PriceWatch assistant" in (res3.chat_reply or "")


@pytest.mark.asyncio
async def test_generate_recommendations_budget_and_trust_ranking():
    svc = ConversationalAdvisorService()

    fake_deals = [
        StoreDeal(
            store_name="Amazon.in",
            product_title="Unknown Shilajit Capsule",
            price_paise=40000,  # ₹400
            mrp_paise=60000,
            available=True,
            url="https://amazon.in/dp/fake1",
        ),
        StoreDeal(
            store_name="Flipkart",
            product_title="Kapiva Pure Himalayan Shilajit Resin 20g",
            price_paise=50000,  # ₹500 - Trusted brand!
            mrp_paise=99900,
            available=True,
            url="https://flipkart.com/p/fake2",
        ),
        StoreDeal(
            store_name="Nutrabay",
            product_title="Expensive Gold Shilajit",
            price_paise=150000,  # ₹1500 - Over budget!
            available=True,
            url="https://nutrabay.com/p/fake3",
        ),
    ]

    with patch("pricewatch.services.advisor_service.search_flipkart", AsyncMock(return_value=[fake_deals[1]])), \
         patch("pricewatch.services.advisor_service.search_amazon", AsyncMock(return_value=[fake_deals[0], fake_deals[2]])), \
         patch("pricewatch.services.advisor_service.search_hyugalife", AsyncMock(return_value=[])), \
         patch("pricewatch.services.advisor_service.search_healthkart", AsyncMock(return_value=[])), \
         patch("pricewatch.services.advisor_service.search_nutrabay", AsyncMock(return_value=[])), \
         patch("pricewatch.services.advisor_service.search_shopify_store", AsyncMock(return_value=[])):

        text, kb = await svc.generate_recommendations(
            category="shilajit",
            max_budget_inr=1000,
            limit=5,
        )

        assert "Top 2 Shilajit Recommendations Under ₹1,000" in text
        # Kapiva is a trusted brand, so it must rank 1st even if ₹500 > ₹400!
        assert "🥇 <b>Kapiva Pure Himalayan Shilajit Resin 20g</b>" in text
        assert "🛡️ <b>Lab-Verified Brand</b>" in text
        # Over budget ₹1500 deal must be excluded
        assert "Expensive Gold Shilajit" not in text
        assert len(kb.inline_keyboard) >= 2


@pytest.mark.asyncio
async def test_plain_text_handler_routes_recommendation():
    update = MagicMock(spec=Update)
    update.effective_chat.id = 1114988070
    update.effective_message.text = "top 5 shilajit under 1000"
    status_msg = AsyncMock()
    update.effective_message.reply_html = AsyncMock(return_value=status_msg)

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {"tracker_service": MagicMock()}
    context.bot.send_chat_action = AsyncMock()

    mock_intent = ChatIntent(
        intent_type="recommendation",
        category="shilajit",
        max_budget_inr=1000,
        limit=5,
        search_query="shilajit",
    )

    with patch("pricewatch.services.advisor_service.advisor_service.parse_chat_intent", AsyncMock(return_value=mock_intent)), \
         patch("pricewatch.services.advisor_service.advisor_service.generate_recommendations", AsyncMock(return_value=("Top Deals Report", MagicMock()))):

        await plain_text_handler(update, context)

        status_msg.edit_text.assert_called_once()
        assert "Top Deals Report" in status_msg.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_plain_text_handler_routes_comparison():
    update = MagicMock(spec=Update)
    update.effective_chat.id = 1114988070
    update.effective_message.text = "Nakpro Perform 1kg unflavoured"
    status_msg = AsyncMock()
    update.effective_message.reply_html = AsyncMock(return_value=status_msg)

    mock_discovery = MagicMock()
    mock_result = ComparisonResult(
        query_title="Nakpro Perform 1kg unflavoured",
        deals=[],
    )
    mock_discovery.compare_query = AsyncMock(return_value=mock_result)

    context = MagicMock()
    context.user_data = {}
    context.bot_data = {
        "tracker_service": MagicMock(),
        "discovery_service": mock_discovery,
    }
    context.bot.send_chat_action = AsyncMock()

    mock_intent = ChatIntent(
        intent_type="comparison",
        search_query="Nakpro Perform 1kg unflavoured",
    )

    with patch("pricewatch.services.advisor_service.advisor_service.parse_chat_intent", AsyncMock(return_value=mock_intent)):
        await plain_text_handler(update, context)

        mock_discovery.compare_query.assert_called_once_with("Nakpro Perform 1kg unflavoured")
        status_msg.edit_text.assert_called_once()
