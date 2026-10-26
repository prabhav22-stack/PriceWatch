"""Unit tests for AmazonFreshProvider using recorded HTML fixtures."""

from pathlib import Path
import pytest
import respx
import httpx

from pricewatch.domain.exceptions import BotBlockedError, PincodeMismatchError
from pricewatch.providers.amazon_fresh import AmazonFreshProvider


FIXTURES_DIR = Path(__file__).parents[2] / "fixtures"


def test_asin_extraction():
    assert (
        AmazonFreshProvider.extract_asin("https://www.amazon.in/dp/B08XYZ1234?ref=nb_sb_noss")
        == "B08XYZ1234"
    )
    assert (
        AmazonFreshProvider.extract_asin("https://www.amazon.in/gp/product/B07ABC9999/")
        == "B07ABC9999"
    )
    assert (
        AmazonFreshProvider.extract_asin("https://www.amazon.in/alm/storefront/B01FRESH01")
        == "B01FRESH01"
    )
    assert (
        AmazonFreshProvider.extract_asin(
            "https://www.amazon.in/Platinum-Protein-Isolate-Digestive-Supplement/dp/B07WZM3714/ref=sr_1_1_in_f3_wg_fs?almBrandId=ctnow&crid=375LWJ6IIK7TO&dib=eyJ2IjoiMSJ9.lQJb6ToDlWiW0AN-zdMdFEy961lfOB74gADp51poKFN0s_bt_Oj9iLMbkaZLthmPCeNI2h457xisIdTlhsCGrlz4ZfOAwCZthTiUeSuBisvN2kQtYg_Xquq_fZJRGEJPCPcEP0NX7Lc8Yu8CQCCqYMyu47CacdveUESIJ_aIo1FRmRiA3IM_0g1AiYCVWbI3p6DJyzvw27sWUq53EXhijnBPlow6dtbY5Qm46klABCBrXmk8ZHWM8NbB8prw0GLXIU7-HichoY30rPgUjXcGX6t7V7F2W4ltAiyt1pzOwds.KXKfYNlj0jKif6w_6lR_9kLmhk7falYHF8n4qRnP5lQ&dib_tag=se&fpw=alm&keywords=Whey%2Bplatinum&qid=1784029969&s=nowstore&sprefix=whey%2Bplatin%2Cnowstore%2C291&sr=1-1&th=1"
        )
        == "B07WZM3714"
    )
    assert (
        AmazonFreshProvider.extract_asin("https://www.amazon.in/gp/aw/d/B07WZM3714?ref=mobile")
        == "B07WZM3714"
    )
    assert AmazonFreshProvider.can_handle("https://amzn.in/d/abcd123")
    assert AmazonFreshProvider.can_handle("https://amzn.to/xyz987")


def test_parse_in_stock_fresh_page():
    html_file = FIXTURES_DIR / "amazon_fresh_in_stock.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    title, selling_paise, mrp_paise, available, verified_pincode = (
        AmazonFreshProvider.parse_html_content(html, target_pincode="842002")
    )

    assert "Amul Taaza" in title
    # Must extract Rs 74.00, NOT the Rs 7.40 / 100ml unit price!
    assert selling_paise == 7400
    assert mrp_paise == 8000
    assert available is True
    assert verified_pincode == "842002"


def test_pincode_mismatch_raises_error():
    html_file = FIXTURES_DIR / "amazon_fresh_pincode_mismatch.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    # Requested 842002, but page displays 560001
    with pytest.raises(PincodeMismatchError) as exc_info:
        AmazonFreshProvider.parse_html_content(html, target_pincode="842002")

    assert "560001" in str(exc_info.value)


def test_captcha_page_raises_bot_blocked():
    html_file = FIXTURES_DIR / "amazon_captcha.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    with pytest.raises(BotBlockedError):
        AmazonFreshProvider.parse_html_content(html)


@pytest.mark.asyncio
async def test_resolve_url_success_fast_path():
    provider = AmazonFreshProvider()
    html_file = FIXTURES_DIR / "amazon_fresh_in_stock.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.get("https://www.amazon.in/dp/B08XYZ1234").mock(
            return_value=httpx.Response(200, text=html)
        )
        result = await provider.resolve_url(
            "https://www.amazon.in/dp/B08XYZ1234", pincode="842002"
        )
        assert result.external_product_id == "B08XYZ1234"
        assert "Amul Taaza" in result.product_title
        assert len(result.variants) == 1
        assert result.variants[0].price_paise == 7400


@pytest.mark.asyncio
async def test_resolve_url_fallback_on_captcha_or_error():
    provider = AmazonFreshProvider()
    captcha_file = FIXTURES_DIR / "amazon_captcha.html"
    with open(captcha_file, "r", encoding="utf-8") as f:
        captcha_html = f.read()

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.get("https://www.amazon.in/dp/B08XYZ1234").mock(
            return_value=httpx.Response(200, text=captcha_html)
        )
        result = await provider.resolve_url(
            "https://www.amazon.in/dp/B08XYZ1234", pincode="842002"
        )
        # Should gracefully onboard with Tier 4 for browser worker
        assert result.external_product_id == "B08XYZ1234"
        assert "Amazon Fresh Product (B08XYZ1234)" in result.product_title
        assert result.variants[0].price_paise is None

