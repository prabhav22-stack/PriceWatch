"""Anti-Detect Stealth Browser Engine.

Combines Camoufox C++ anti-fingerprinting Firefox with Playwright Chromium
stealth fallback, providing anti-bot evasion for Amul and complex dynamic stores.
"""

import sys
from typing import Optional
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from pricewatch.logging_setup import get_logger

logger = get_logger("stealth_browser")

# Ensure PyYAML compatibility across all Python versions
try:
    import yaml
    if not hasattr(yaml, "CLoader"):
        yaml.CLoader = yaml.Loader
    if not hasattr(yaml, "CDumper"):
        yaml.CDumper = yaml.Dumper
except Exception:
    pass


class StealthBrowserManager:
    """Manages stealth browser sessions with graceful fallback."""

    @staticmethod
    async def fetch_page_content(
        url: str,
        wait_selector: Optional[str] = None,
        timeout_ms: int = 25000,
        headless: bool = True,
    ) -> str:
        """
        Fetch dynamic rendered page content using stealth browser.
        Attempts Camoufox first, falling back to Playwright stealth Chromium.
        """
        # 1. Attempt Camoufox
        try:
            from camoufox.async_api import AsyncCamoufox

            logger.debug("Attempting stealth fetch with Camoufox", url=url)
            async with AsyncCamoufox(headless=headless, humanize=False) as browser:
                page = await browser.new_page()
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=8000)
                    except Exception:
                        pass
                content = await page.content()
                logger.info("Successfully fetched page with Camoufox", url=url, length=len(content))
                return content
        except Exception as exc:
            logger.warning(
                "Camoufox launch or fetch failed, falling back to Playwright Chromium stealth",
                error=str(exc),
            )

        # 2. Resilient Playwright Chromium fallback with stealth arguments
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            page = await context.new_page()
            # Remove navigator.webdriver flag
            await page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass

            content = await page.content()
            await browser.close()
            return content
