"""Unit tests for GenericProvider with JSON-LD structured data."""

from pathlib import Path
import pytest
import respx
import httpx

from pricewatch.providers.generic import GenericProvider


FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "generic_product_ldjson.html"


@respx.mock
@pytest.mark.asyncio
async def test_generic_json_ld_extraction():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    url = "https://example-supplements.in/products/gold-standard-whey"
    respx.get(url).mock(return_value=httpx.Response(200, text=html))

    provider = GenericProvider()
    result = await provider.resolve_url(url)

    assert result.product_title == "Optimum Nutrition Gold Standard 100% Whey"
    assert result.variants[0].price_paise == 329900
    assert result.variants[0].available is True
