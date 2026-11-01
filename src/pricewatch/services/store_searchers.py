"""Parallel multi-store searchers querying trusted Indian fitness & nutrition platforms."""

import asyncio
import json
import urllib.parse
from typing import Any, Dict, List, Optional
from selectolax.lexbor import LexborHTMLParser

from pricewatch.core.cache import cache
from pricewatch.domain.models import StoreDeal
from pricewatch.logging_setup import get_logger
from pricewatch.providers.http_client import http_client
from pricewatch.services.discovery_matcher import (
    compute_match_score,
    extract_brand,
    extract_weight_in_grams,
)
from pricewatch.validation.normalizer import parse_inr_to_paise

logger = get_logger("store_searchers")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


async def search_hyugalife(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Search HyugaLife via Next.js server-rendered catalog."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://hyugalife.com/search?q={enc_q}"

    try:
        resp = await http_client.get(url, headers=_DEFAULT_HEADERS, timeout=6.0)
        if resp.status_code != 200:
            return deals

        parser = LexborHTMLParser(resp.text)
        script = parser.css_first('script#__NEXT_DATA__')
        if not script:
            return deals

        data = json.loads(script.text())
        items = (
            data.get("props", {})
            .get("pageProps", {})
            .get("listingData", {})
            .get("data", {})
            .get("items", [])
        )

        for it in items[:15]:
            name = it.get("name") or ""
            if not name:
                continue

            # Price extraction (HyugaLife prices are in rupees, e.g. 449 or 449.00)
            raw_sp = it.get("special_price") or it.get("price") or 0
            raw_mrp = it.get("price")
            price_paise = parse_inr_to_paise(str(raw_sp)) or 0
            mrp_paise = parse_inr_to_paise(str(raw_mrp)) if raw_mrp else None

            # Stock status
            is_in_stock = (it.get("stock_status") == "IN_STOCK")
            url_key = it.get("url_key") or ""
            deal_url = f"https://hyugalife.com/product/{url_key}" if url_key else url
            brand = it.get("brand") or ""

            cand_weight = extract_weight_in_grams(name)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=name,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
                candidate_brand=brand,
            )

            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name="HyugaLife",
                        product_title=name,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        mrp_paise=mrp_paise,
                        available=is_in_stock,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("HyugaLife search encountered error", query=query, error=str(exc))

    return deals


async def search_healthkart(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Search HealthKart via Next.js SSR catalog."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://www.healthkart.com/search?txtQ={enc_q}"

    try:
        resp = await http_client.get(url, headers=_DEFAULT_HEADERS, timeout=6.0)
        if resp.status_code != 200:
            return deals

        parser = LexborHTMLParser(resp.text)
        script = parser.css_first('script#__NEXT_DATA__')
        if not script:
            return deals

        data = json.loads(script.text())
        variants = (
            data.get("props", {})
            .get("pageProps", {})
            .get("catL2ResultsSSRData", {})
            .get("variants", [])
        )

        for v in variants[:15]:
            name = v.get("nm") or v.get("name") or ""
            if not name:
                continue

            raw_sp = v.get("offerPrice") or v.get("pr") or 0
            raw_mrp = v.get("mrp")
            price_paise = parse_inr_to_paise(str(raw_sp)) or 0
            mrp_paise = parse_inr_to_paise(str(raw_mrp)) if raw_mrp else None

            is_in_stock = not bool(v.get("oos", False))
            path = v.get("url") or ""
            deal_url = f"https://www.healthkart.com{path}" if path.startswith("/") else (path or url)
            brand = v.get("brandName") or v.get("brName") or ""

            cand_weight = extract_weight_in_grams(name)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=name,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
                candidate_brand=brand,
            )

            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name="HealthKart",
                        product_title=name,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        mrp_paise=mrp_paise,
                        available=is_in_stock,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("HealthKart search encountered error", query=query, error=str(exc))

    return deals


async def search_shopify_store(
    domain: str,
    store_label: str,
    query: str,
    target_weight_g: Optional[int] = None,
) -> List[StoreDeal]:
    """Search a direct Shopify D2C brand store using the predictive search API."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://{domain}/search/suggest.json?q={enc_q}&resources[type]=product"

    try:
        resp = await http_client.get(url, headers=_DEFAULT_HEADERS, timeout=5.0)
        if resp.status_code != 200:
            return deals

        data = resp.json()
        products = data.get("resources", {}).get("results", {}).get("products", [])

        for p in products[:10]:
            title = p.get("title") or ""
            if not title:
                continue

            raw_price = p.get("price") or 0
            price_paise = parse_inr_to_paise(str(raw_price)) or 0
            raw_compare = p.get("compare_at_price_max") or p.get("compare_at_price")
            mrp_paise = parse_inr_to_paise(str(raw_compare)) if raw_compare else None

            # Available flag
            available = bool(p.get("available", True))
            path = p.get("url") or ""
            deal_url = f"https://{domain}{path}" if path.startswith("/") else f"https://{domain}/products/{p.get('handle', '')}"

            cand_weight = extract_weight_in_grams(title)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=title,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
            )

            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name=store_label,
                        product_title=title,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        mrp_paise=mrp_paise,
                        available=available,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("Shopify store search encountered error", domain=domain, error=str(exc))

    return deals


def _search_amazon_sync(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Execute synchronous Amazon search with browser TLS impersonation via curl_cffi."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://www.amazon.in/s?k={enc_q}"
    try:
        from curl_cffi import requests
        r = requests.get(url, impersonate="chrome124", timeout=8)
        if r.status_code != 200:
            return deals

        parser = LexborHTMLParser(r.text)
        items = parser.css('div[data-component-type="s-search-result"]')
        for it in items[:15]:
            h2 = it.css_first("h2")
            title = h2.text(strip=True) if h2 else ""
            if not title:
                continue

            price_node = it.css_first(".a-price .a-offscreen")
            price_text = price_node.text(strip=True) if price_node else ""
            price_paise = parse_inr_to_paise(price_text) or 0

            asin = it.attributes.get("data-asin", "")
            deal_url = f"https://www.amazon.in/dp/{asin}" if asin else url

            cand_weight = extract_weight_in_grams(title)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=title,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
            )
            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name="Amazon.in",
                        product_title=title,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        available=True,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("Amazon search encountered error", query=query, error=str(exc))
    return deals


async def search_amazon(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Asynchronously search Amazon.in without blocking the event loop."""
    return await asyncio.to_thread(_search_amazon_sync, query, target_weight_g)


def _search_flipkart_sync(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Execute synchronous Flipkart search with browser TLS impersonation via curl_cffi."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://www.flipkart.com/search?q={enc_q}"
    try:
        from curl_cffi import requests
        r = requests.get(url, impersonate="chrome124", timeout=8)
        if r.status_code != 200:
            return deals

        parser = LexborHTMLParser(r.text)
        cards = parser.css('[data-id]')
        for c in cards[:15]:
            title_elem = c.css_first('a[title]')
            title = (
                title_elem.attributes.get('title')
                if title_elem
                else (c.css_first('.wjcEIp') or c.css_first('.KzDlHZ') or c.css_first('.s1Q9rs'))
            )
            if hasattr(title, 'text'):
                title = title.text(strip=True)
            if not title:
                continue

            price_node = c.css_first('div._30jeq3') or c.css_first('div.Nx9bqj')
            if not price_node:
                for d in c.css('div'):
                    t = d.text(strip=True)
                    if '₹' in t and len(t) < 15:
                        price_node = d
                        break
            price_text = price_node.text(strip=True) if price_node else ""
            price_paise = parse_inr_to_paise(price_text) or 0

            link = c.css_first('a[href*="/p/"]')
            href = link.attributes.get('href', "") if link else ""
            deal_url = f"https://www.flipkart.com{href.split('?')[0]}" if href else url

            cand_weight = extract_weight_in_grams(title)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=title,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
            )
            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name="Flipkart",
                        product_title=title,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        available=True,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("Flipkart search encountered error", query=query, error=str(exc))
    return deals


async def search_flipkart(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Asynchronously search Flipkart without blocking the event loop."""
    return await asyncio.to_thread(_search_flipkart_sync, query, target_weight_g)


async def search_muscleblaze(query: str, target_weight_g: Optional[int] = None) -> List[StoreDeal]:
    """Search MuscleBlaze direct store catalog."""
    deals: List[StoreDeal] = []
    enc_q = urllib.parse.quote_plus(query)
    url = f"https://www.muscleblaze.com/search?txtQ={enc_q}"

    try:
        resp = await http_client.get(url, headers=_DEFAULT_HEADERS, timeout=6.0)
        if resp.status_code != 200:
            return deals

        parser = LexborHTMLParser(resp.text)
        script = parser.css_first('script#__NEXT_DATA__')
        if not script:
            return deals

        data = json.loads(script.text())
        variants = (
            data.get("props", {})
            .get("pageProps", {})
            .get("catL2ResultsSSRData", {})
            .get("variants", [])
        )

        for v in variants[:10]:
            name = v.get("nm") or v.get("name") or ""
            if not name:
                continue

            raw_sp = v.get("offerPrice") or v.get("pr") or 0
            raw_mrp = v.get("mrp")
            price_paise = parse_inr_to_paise(str(raw_sp)) or 0
            mrp_paise = parse_inr_to_paise(str(raw_mrp)) if raw_mrp else None

            is_in_stock = not bool(v.get("oos", False))
            path = v.get("url") or ""
            deal_url = f"https://www.muscleblaze.com{path}" if path.startswith("/") else (path or url)

            cand_weight = extract_weight_in_grams(name)
            score, is_ok = compute_match_score(
                query_title=query,
                candidate_title=name,
                target_weight_g=target_weight_g,
                candidate_weight_g=cand_weight,
                candidate_brand="muscleblaze",
            )

            if is_ok and price_paise > 0:
                p100g = int(round(price_paise * 100.0 / cand_weight)) if cand_weight else None
                deals.append(
                    StoreDeal(
                        store_name="MuscleBlaze",
                        product_title=name,
                        variant_title=f"{cand_weight}g" if cand_weight else "",
                        price_paise=price_paise,
                        mrp_paise=mrp_paise,
                        available=is_in_stock,
                        url=deal_url,
                        match_score=score,
                        spec_weight_g=cand_weight,
                        price_per_100g_paise=p100g,
                    )
                )
    except Exception as exc:
        logger.debug("MuscleBlaze search encountered error", query=query, error=str(exc))

    return deals


@cache(ttl="3m", key="all_stores:{query}:{target_weight_g}", lock=True)
async def query_all_stores(
    query: str,
    target_weight_g: Optional[int] = None,
) -> List[StoreDeal]:
    """Query all trusted stores concurrently and return combined candidate deals."""
    tasks = [
        search_flipkart(query, target_weight_g=target_weight_g),
        search_amazon(query, target_weight_g=target_weight_g),
        search_hyugalife(query, target_weight_g=target_weight_g),
        search_healthkart(query, target_weight_g=target_weight_g),
        search_muscleblaze(query, target_weight_g=target_weight_g),
        search_shopify_store("nakpro.com", "Nakpro Direct", query, target_weight_g=target_weight_g),
        search_shopify_store("asitisnutrition.com", "AS-IT-IS Direct", query, target_weight_g=target_weight_g),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_deals: List[StoreDeal] = []

    for r in results:
        if isinstance(r, list):
            all_deals.extend(r)
        elif isinstance(r, Exception):
            logger.warning("One store searcher raised exception", error=str(r))

    return all_deals
