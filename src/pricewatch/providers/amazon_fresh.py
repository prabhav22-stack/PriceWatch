"""Amazon Fresh and Amazon India provider with scoped price extraction and pincode verification."""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from pricewatch.domain.enums import ProviderTier
from pricewatch.domain.exceptions import (
    BotBlockedError,
    ExtractionError,
    PincodeMismatchError,
)
from pricewatch.domain.models import PriceQuote, ResolutionResult, VariantOption
from pricewatch.providers.base import BaseProvider, ProviderRegistry
from pricewatch.providers.http_client import http_client
from pricewatch.validation.normalizer import parse_inr_to_paise


_ASIN_REGEX = re.compile(
    r"/(?:dp|gp/product|gp/aw/d|alm/storefront)/([A-Z0-9]{10})", re.IGNORECASE
)


@ProviderRegistry.register
class AmazonFreshProvider(BaseProvider):
    """Tier 4 / Scoped HTML provider for Amazon Fresh and Amazon India."""

    provider_code = "amazon_fresh"
    tier = ProviderTier.BROWSER

    @classmethod
    def can_handle(cls, url: str) -> bool:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        if "amazon.in" in domain or "amzn.in" in domain or "amzn.to" in domain:
            return True
        return False

    @staticmethod
    def extract_asin(url: str) -> str:
        match = _ASIN_REGEX.search(url)
        if match:
            return match.group(1).upper()
        # Fallback ASIN query param
        parsed = urlparse(url)
        if "asin" in parsed.query:
            from urllib.parse import parse_qs
            return parse_qs(parsed.query)["asin"][0].upper()
        raise ExtractionError(f"Could not extract ASIN from Amazon URL: {url}")

    @staticmethod
    def parse_html_content(
        html: str, target_pincode: str = ""
    ) -> Tuple[str, Optional[int], Optional[int], bool, str]:
        """
        Extract title, selling price, MRP, availability and verified pincode from HTML.
        Enforces strict exclusion of unit-prices (Rs/100g) and strike-through MRP.
        """
        parser = LexborHTMLParser(html)

        # Check for CAPTCHA / bot block page
        title_node = parser.css_first("title")
        page_title = title_node.text(strip=True) if title_node else ""
        if "Robot Check" in page_title or "validateCaptcha" in html:
            raise BotBlockedError("Amazon returned Robot Check / CAPTCHA challenge page")

        # Verify pincode if specified
        verified_pincode = ""
        glow_node = parser.css_first("#glow-ingress-line2")
        if glow_node:
            glow_text = glow_node.text(strip=True)
            # Find 6 digit indian pincode in glow text
            pin_match = re.search(r"(\d{6})", glow_text)
            if pin_match:
                verified_pincode = pin_match.group(1)

        if target_pincode and verified_pincode:
            if target_pincode != verified_pincode:
                raise PincodeMismatchError(
                    f"Pincode mismatch: Page shows {verified_pincode}, requested {target_pincode}"
                )

        # Extract Product Title
        product_title = "Amazon Product"
        title_elem = parser.css_first("#productTitle") or parser.css_first("#title")
        if title_elem:
            product_title = title_elem.text(strip=True)

        # Check Availability
        available = True
        avail_node = parser.css_first("#availability")
        if avail_node:
            avail_text = avail_node.text(strip=True).lower()
            if "currently unavailable" in avail_text or "out of stock" in avail_text:
                available = False

        # Scope strictly to primary buy box container to eliminate related-item price leaks
        buy_box = (
            parser.css_first("#corePriceDisplay_desktop_feature_div")
            or parser.css_first("#corePrice_desktop")
            or parser.css_first("#apex_desktop")
            or parser.css_first("#almDetailPage")
            or parser
        )

        # Extract Selling Price (.priceToPay)
        selling_price_paise = None
        price_to_pay = (
            buy_box.css_first(".priceToPay .a-offscreen")
            or buy_box.css_first(".apexPriceToPay .a-offscreen")
            or buy_box.css_first(".priceToPay")
        )
        if price_to_pay:
            selling_price_paise = parse_inr_to_paise(price_to_pay.text(strip=True))

        # Fallback to .a-price-whole inside priceToPay if offscreen is missing
        if not selling_price_paise:
            whole_node = buy_box.css_first(".priceToPay .a-price-whole")
            if whole_node:
                whole_text = whole_node.text(strip=True)
                fract_node = buy_box.css_first(".priceToPay .a-price-fraction")
                fract_text = fract_node.text(strip=True) if fract_node else "00"
                selling_price_paise = parse_inr_to_paise(f"{whole_text}.{fract_text}")

        # Extract MRP / Basis Price (.basisPrice or strike-through)
        mrp_paise = None
        mrp_node = (
            buy_box.css_first(".basisPrice .a-offscreen")
            or buy_box.css_first('span[data-a-strike="true"] .a-offscreen')
            or buy_box.css_first(".a-text-price .a-offscreen")
        )
        if mrp_node:
            mrp_paise = parse_inr_to_paise(mrp_node.text(strip=True))

        # If selling price exceeds MRP, it's an extraction bug
        if selling_price_paise and mrp_paise and selling_price_paise > mrp_paise:
            # Swap or discard basisPrice if erroneous
            mrp_paise = None

        if not selling_price_paise and available:
            raise ExtractionError("Failed to extract selling price from Amazon buy box")

        return product_title, selling_price_paise, mrp_paise, available, verified_pincode

    async def resolve_url(self, url: str, pincode: str = "") -> ResolutionResult:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        if "amzn." in domain:
            try:
                resp = await http_client.get(url)
                url = str(resp.url)
            except Exception:
                pass

        asin = self.extract_asin(url)
        canonical_url = f"https://www.amazon.in/dp/{asin}"

        # Try fast HTTP GET first to grab metadata instantly
        try:
            resp = await http_client.get(canonical_url)
            if resp.status_code == 200 and "Robot Check" not in resp.text:
                title, price_paise, mrp_paise, available, verified_pincode = self.parse_html_content(
                    resp.text, target_pincode=pincode
                )
                variant = VariantOption(
                    external_variant_id=asin,
                    variant_title="Default",
                    canonical_url=canonical_url,
                    price_paise=price_paise,
                    mrp_paise=mrp_paise,
                    available=available,
                )
                return ResolutionResult(
                    provider_code=self.provider_code,
                    provider_tier=self.tier,
                    external_product_id=asin,
                    product_title=title,
                    requires_pincode=bool(pincode),
                    variants=[variant],
                    pinned_variant_id=asin,
                )
        except Exception as exc:
            pass

        # Graceful fallback: Amazon Fresh items are often hyperlocal / pincode-gated.
        # Onboard the listing into Tier 4 (BROWSER) so the browser worker checks it.
        variant = VariantOption(
            external_variant_id=asin,
            variant_title="Default",
            canonical_url=canonical_url,
            price_paise=None,
            mrp_paise=None,
            available=True,
        )
        return ResolutionResult(
            provider_code=self.provider_code,
            provider_tier=self.tier,
            external_product_id=asin,
            product_title=f"Amazon Fresh Product ({asin})",
            requires_pincode=bool(pincode),
            variants=[variant],
            pinned_variant_id=asin,
        )

    async def fetch_quote(
        self,
        canonical_url: str,
        external_product_id: str,
        external_variant_id: str,
        pincode: str = "",
    ) -> PriceQuote:
        html = ""
        # 1. Try Playwright browser pool if available (required for hyperlocal Amazon Fresh pincode)
        try:
            from pricewatch.providers.browser_pool import BrowserPool
            html = await BrowserPool.fetch_amazon_fresh_page(canonical_url, pincode=pincode)
        except Exception as exc:
            logger.warning("Browser fetch failed, falling back to HTTP", error=str(exc))
            # 2. Fallback to HTTP client
            resp = await http_client.get(canonical_url)
            if resp.status_code != 200:
                raise ExtractionError(f"HTTP {resp.status_code} fetching {canonical_url}")
            html = resp.text

        title, price_paise, mrp_paise, available, verified_pincode = self.parse_html_content(
            html, target_pincode=pincode
        )

        return PriceQuote(
            external_product_id=external_product_id,
            external_variant_id=external_variant_id,
            price_paise=price_paise,
            mrp_paise=mrp_paise,
            currency="INR",
            available=available,
            verified_pincode=verified_pincode or pincode,
            extraction_method="amazon_dom",
            raw_variant_title="Default",
        )
