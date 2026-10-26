"""Unit tests for ShopifyProvider using recorded JSON fixtures."""

from pathlib import Path
import pytest
import respx
import httpx

from pricewatch.domain.exceptions import VariantAmbiguousError, VariantNotFoundError
from pricewatch.providers.shopify import ShopifyProvider


FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "nakpro_whey_multi_variant.json"


@pytest.fixture
def nakpro_json():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_shopify_can_handle():
    assert ShopifyProvider.can_handle("https://nakpro.com/products/impact-whey-protein") is True
    assert ShopifyProvider.can_handle("https://www.muscleblaze.com/products/biozyme-whey") is True
    assert ShopifyProvider.can_handle("https://customstore.in/products/item-123") is True
    assert ShopifyProvider.can_handle("https://amazon.in/dp/B08XYZ1234") is False


@respx.mock
@pytest.mark.asyncio
async def test_resolve_url_ambiguous_variant(nakpro_json):
    url = "https://nakpro.com/products/impact-whey-protein"
    respx.get("https://nakpro.com/products/impact-whey-protein.js").mock(
        return_value=httpx.Response(200, text=nakpro_json)
    )

    provider = ShopifyProvider()
    with pytest.raises(VariantAmbiguousError) as exc_info:
        await provider.resolve_url(url)

    assert len(exc_info.value.variants) == 3
    assert exc_info.value.variants[0].external_variant_id == "40987654321"
    assert exc_info.value.variants[0].price_paise == 134900


@respx.mock
@pytest.mark.asyncio
async def test_resolve_url_explicit_pinned_variant(nakpro_json):
    url = "https://nakpro.com/products/impact-whey-protein?variant=40987654322"
    respx.get("https://nakpro.com/products/impact-whey-protein.js").mock(
        return_value=httpx.Response(200, text=nakpro_json)
    )

    provider = ShopifyProvider()
    result = await provider.resolve_url(url)

    assert result.pinned_variant_id == "40987654322"
    assert result.product_title == "Nakpro Impact Whey Protein"
    assert result.provider_code == "shopify:nakpro.com"


@respx.mock
@pytest.mark.asyncio
async def test_resolve_url_missing_variant(nakpro_json):
    url = "https://nakpro.com/products/impact-whey-protein?variant=99999999999"
    respx.get("https://nakpro.com/products/impact-whey-protein.js").mock(
        return_value=httpx.Response(200, text=nakpro_json)
    )

    provider = ShopifyProvider()
    with pytest.raises(VariantNotFoundError):
        await provider.resolve_url(url)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_quote_success(nakpro_json):
    url = "https://nakpro.com/products/impact-whey-protein?variant=40987654321"
    respx.get("https://nakpro.com/products/impact-whey-protein.js").mock(
        return_value=httpx.Response(200, text=nakpro_json)
    )

    provider = ShopifyProvider()
    quote = await provider.fetch_quote(
        canonical_url=url,
        external_product_id="impact-whey-protein",
        external_variant_id="40987654321",
    )

    assert quote.external_variant_id == "40987654321"
    assert quote.price_paise == 134900
    assert quote.mrp_paise == 199900
    assert quote.available is True
    assert quote.extraction_method == "shopify_js"
