"""Unit tests for:
1. DealScorer & Fake Discount Detector (PriceDive pattern)
2. VisionExtractor & Photo Message Handler
3. Prometheus Metrics Endpoint
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from pricewatch.bot.handlers.commands import photo_message_handler
from pricewatch.domain.models import ComparisonResult, StoreDeal
from pricewatch.services.deal_scorer import DealEvaluation, DealScorer
from pricewatch.services.vision_extractor import VisionExtractedProduct, VisionExtractor
from pricewatch.webapp.server import app


def test_deal_scorer_historic_low():
    """Verify historic low gives a 10/10 score."""
    history = {
        "min_price": 200000,
        "max_price": 250000,
        "avg_price": 225000,
        "median_price": 225000,
        "count": 30,
    }
    evaluation = DealScorer.evaluate_deal(
        current_price_paise=190000,
        mrp_paise=300000,
        history_summary_30d=history,
    )
    assert evaluation.deal_score == 10
    assert "Historic Low" in evaluation.rating_label
    assert evaluation.is_fake_discount is False


def test_deal_scorer_fake_discount():
    """Verify inflated MRP with average selling price triggers fake discount alert."""
    history = {
        "min_price": 180000,
        "max_price": 220000,
        "avg_price": 200000,
        "median_price": 200000,
        "count": 30,
    }
    # Seller sets MRP to 4500 (inflated > 100% vs historical max of 2200), but sells at 2100
    evaluation = DealScorer.evaluate_deal(
        current_price_paise=210000,
        mrp_paise=450000,
        history_summary_30d=history,
    )
    assert evaluation.is_fake_discount is True
    assert evaluation.deal_score <= 4
    assert "Fake Discount" in evaluation.rating_label
    assert evaluation.mrp_inflation_pct > 30.0


def test_deal_scorer_expensive_price():
    """Verify price above average gets an expensive rating."""
    history = {
        "min_price": 180000,
        "max_price": 220000,
        "avg_price": 190000,
        "median_price": 190000,
        "count": 30,
    }
    evaluation = DealScorer.evaluate_deal(
        current_price_paise=230000,
        mrp_paise=250000,
        history_summary_30d=history,
    )
    assert evaluation.deal_score == 4
    assert "Expensive" in evaluation.rating_label


@pytest.mark.asyncio
async def test_vision_extractor_parser():
    """Verify VisionExtractor parses Gemini JSON response cleanly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                '{"title": "Nakpro Perform Whey", "brand": "Nakpro", '
                                '"variant": "1kg Chocolate", "weight_g": 1000, '
                                '"price_inr": 2089.0, "store": "Amazon"}'
                            )
                        }
                    ]
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with patch("pricewatch.config.settings.GEMINI_API_KEY", "mock_key"):
            extracted = await VisionExtractor.extract_from_image_bytes(b"fake_bytes")
            assert extracted is not None
            assert extracted.title == "Nakpro Perform Whey"
            assert extracted.brand == "Nakpro"
            assert extracted.weight_g == 1000
            assert extracted.price_paise == 208900
            assert extracted.detected_store == "Amazon"


@pytest.mark.asyncio
async def test_photo_message_handler():
    """Verify photo message handler processes incoming screenshots."""
    update = MagicMock()
    update.effective_user.id = 555
    update.effective_message.reply_html = AsyncMock()
    status_mock = AsyncMock()
    update.effective_message.reply_html.return_value = status_mock

    photo_mock = MagicMock()
    file_mock = AsyncMock()
    file_mock.download_as_bytearray.return_value = bytearray(b"dummy_img")
    photo_mock.get_file = AsyncMock(return_value=file_mock)
    update.message.photo = [photo_mock]

    context = MagicMock()
    context.bot_data = {}

    extracted = VisionExtractedProduct(
        title="Optimum Nutrition Gold Standard Whey",
        brand="ON",
        variant="2kg",
        weight_g=2000,
        price_paise=650000,
    )

    with patch("pricewatch.services.vision_extractor.VisionExtractor.extract_from_image_bytes", new_callable=AsyncMock) as mock_vision:
        mock_vision.return_value = extracted
        with patch("pricewatch.services.discovery_service.DiscoveryService.compare_query", new_callable=AsyncMock) as mock_cmp:
            best_deal = StoreDeal(
                store_name="Flipkart",
                product_title="Optimum Nutrition Gold Standard Whey 2kg",
                price_paise=620000,
                available=True,
                url="https://flipkart.com/on/p/123",
            )
            mock_cmp.return_value = ComparisonResult(
                query_title="Optimum Nutrition Gold Standard Whey 2kg",
                deals=[best_deal],
                cheapest_deal=best_deal,
                in_stock_count=1,
                total_stores_checked=5,
            )

            await photo_message_handler(update, context)

            status_mock.edit_text.assert_called_once()
            output_msg = status_mock.edit_text.call_args[0][0]
            assert "Product Detected via AI Vision" in output_msg
            assert "Optimum Nutrition Gold Standard Whey" in output_msg


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint():
    """Verify Prometheus /metrics returns scrapable metrics."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "pricewatch_active_listings_count" in resp.text
        assert "pricewatch_http_requests_total" in resp.text
