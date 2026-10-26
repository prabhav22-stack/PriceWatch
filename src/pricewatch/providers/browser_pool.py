"""Playwright browser pool with resource-blocking and pincode negotiation for Amazon Fresh."""

import asyncio
import re
from typing import Optional
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from pricewatch.domain.exceptions import BotBlockedError, ExtractionError, PincodeMismatchError
from pricewatch.logging_setup import get_logger

logger = get_logger("browser_pool")

class BrowserPool:
    """Manages lightweight headless Chromium contexts with pincode session reuse."""

    @staticmethod
    async def fetch_amazon_fresh_page(url: str, pincode: str = "") -> str:
        """
        Launch lightweight headless browser context, set pincode if specified,
        and return the fully rendered HTML.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )

            page = await context.new_page()
            # Mask headless webdriver detection
            await page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

            try:
                # 1. Navigate directly to target product page
                logger.info("Navigating to Amazon product page", url=url)
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(1000)

                title = await page.title()
                if "Robot Check" in title:
                    raise BotBlockedError("Amazon returned Robot Check / CAPTCHA challenge")

                # 2. If pincode is specified, set delivery pincode directly on the product page
                if pincode:
                    glow_text = ""
                    glow_elem = await page.query_selector("#glow-ingress-line2")
                    if glow_elem:
                        glow_text = (await glow_elem.inner_text()) or ""

                    if pincode not in glow_text:
                        logger.info("Setting Amazon delivery pincode in browser session", pincode=pincode)
                        popover = await page.query_selector("#nav-global-location-popover-link") or await page.query_selector("#contextualIngressPt")
                        if popover:
                            try:
                                await popover.click()
                                await page.wait_for_selector("#GLUXZipUpdateInput", timeout=5000)
                                await page.fill("#GLUXZipUpdateInput", pincode)
                                span = (
                                    await page.query_selector("[data-action='GLUXPostalUpdateAction']")
                                    or await page.query_selector("#GLUXZipUpdate-announce")
                                    or await page.query_selector("#GLUXZipUpdate")
                                )
                                if span:
                                    await span.click()
                                    # Wait for Amazon to update location label and condo buy box
                                    await page.wait_for_timeout(3000)

                                g_elem = await page.query_selector("#glow-ingress-line2")
                                if g_elem:
                                    g_text = await g_elem.inner_text()
                                    logger.info("Updated delivery pincode in browser", glow_text=g_text)
                            except Exception as pin_exc:
                                logger.warning("Could not interact with pincode modal", error=str(pin_exc))

                html = await page.content()
                return html

            finally:
                await context.close()
                await browser.close()
