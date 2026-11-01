"""Multimodal Vision & Screenshot Product Extractor.

Extracts product brand, title, variant, weight, and visible price from uploaded photos
or screenshots using Gemini Vision REST API when configured, with seamless offline
Windows Native OCR fallback (winocr / Windows.Media.Ocr).
"""

import base64
import io
import json
import re
from dataclasses import dataclass
from typing import List, Optional
import httpx
from PIL import Image

from pricewatch.config import settings
from pricewatch.logging_setup import get_logger
from pricewatch.services.discovery_matcher import (
    CORE_PRODUCT_CATEGORIES,
    extract_brand,
    extract_weight_in_grams,
)
from pricewatch.validation.normalizer import parse_inr_to_paise

logger = get_logger("vision_extractor")

# UI noise terms to ignore when extracting product titles from screenshots
_UI_NOISE_TERMS = {
    "open ", "view on", "best available", "stores comparison", "cheapest",
    "in stock", "out of stock", "telegram", "all chats", "personal",
    "tracked items", "main menu", "tap a store", "tap below", "http",
    "www.", "search chats", "price & stock", "status", "settings",
}


@dataclass(frozen=True)
class VisionExtractedProduct:
    title: str
    brand: Optional[str] = None
    variant: Optional[str] = None
    weight_g: Optional[int] = None
    price_paise: Optional[int] = None
    detected_store: Optional[str] = None
    confidence: float = 0.85


class VisionExtractor:
    """Extracts product information from screenshots or photos."""

    @classmethod
    async def extract_from_image_bytes(
        cls, image_bytes: bytes, mime_type: str = "image/jpeg"
    ) -> Optional[VisionExtractedProduct]:
        """Extract product info: tries Gemini Vision first, falls back to local offline OCR."""
        api_key = settings.GEMINI_API_KEY
        if api_key:
            try:
                gemini_product = await cls._extract_via_gemini(image_bytes, api_key, mime_type)
                if gemini_product and gemini_product.title:
                    return gemini_product
            except Exception as exc:
                logger.warning("Gemini Vision API encountered error, falling back to local OCR", error=str(exc))

        # Fallback to local offline OCR
        return await cls._extract_via_local_ocr(image_bytes)

    @classmethod
    async def _extract_via_gemini(
        cls, image_bytes: bytes, api_key: str, mime_type: str
    ) -> Optional[VisionExtractedProduct]:
        """Send image to Gemini Multimodal Vision API and parse product specs."""
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        model = getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        prompt = (
            "Analyze this product screenshot or photo. "
            "Extract the exact product title, brand name, variant/flavor, weight in grams (e.g. 1000 for 1kg), "
            "visible selling price in INR, and store name if visible (e.g. Amazon, Flipkart, Nutrabay, Amul, MuscleBlaze). "
            "Output ONLY a valid JSON object matching this schema: "
            "{\"title\": string, \"brand\": string, \"variant\": string, \"weight_g\": number or null, \"price_inr\": number or null, \"store\": string or null}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_data,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Gemini Vision API request failed", status=resp.status_code, text=resp.text[:200])
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text_content:
                return None

            parsed = json.loads(text_content.strip())
            title = parsed.get("title") or ""
            if not title:
                return None

            brand = parsed.get("brand") or extract_brand(title)
            variant = parsed.get("variant")
            weight_g = parsed.get("weight_g")
            price_inr = parsed.get("price_inr")
            price_paise = int(round(price_inr * 100)) if price_inr else None
            store = parsed.get("store")

            return VisionExtractedProduct(
                title=title,
                brand=brand,
                variant=variant,
                weight_g=int(weight_g) if weight_g else extract_weight_in_grams(title),
                price_paise=price_paise,
                detected_store=store,
                confidence=0.92,
            )

    @classmethod
    async def _extract_via_local_ocr(cls, image_bytes: bytes) -> Optional[VisionExtractedProduct]:
        """Extract product info offline using multiplatform OCR (winocr, pytesseract, or PaddleOCR)."""
        lines: List[str] = []
        full_text: str = ""

        # Tier 1: Windows Native OCR (winocr)
        try:
            import winocr
            img = Image.open(io.BytesIO(image_bytes))
            ocr_res = await winocr.recognize_pil(img)
            lines = [l.text.strip() for l in ocr_res.lines if l.text.strip()]
            full_text = ocr_res.text or " ".join(lines)
        except Exception:
            pass

        # Tier 2: pytesseract (Cross-platform Linux / Windows fallback)
        if not lines:
            try:
                import pytesseract
                img = Image.open(io.BytesIO(image_bytes))
                raw_text = pytesseract.image_to_string(img)
                lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
                full_text = " ".join(lines)
            except Exception:
                pass

        # Tier 3: PaddleOCR (Lightweight CPU OCR fallback)
        if not lines:
            try:
                from paddleocr import PaddleOCR
                import numpy as np
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                img_np = np.array(img)
                ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
                result = ocr.ocr(img_np, cls=False)
                if result and result[0]:
                    for line_data in result[0]:
                        txt = line_data[1][0].strip()
                        if txt:
                            lines.append(txt)
                    full_text = " ".join(lines)
            except Exception:
                pass

        if not lines:
            return None

        try:
            title: Optional[str] = None
            detected_brand: Optional[str] = None
            detected_store: Optional[str] = None
            price_paise: Optional[int] = None

            # 1. Look for explicit product label in chat / UI: "Product: <Name>"
            for line in lines:
                m_prod = re.match(r"^(?:Product|Item|Title):\s*(.+)$", line, re.IGNORECASE)
                if m_prod:
                    cand = m_prod.group(1).strip()
                    # Clean any trailing status or buttons appended in same line
                    cand = re.sub(r"\s*(?:Best Available|Stores Comparison|\(In Stock\)|₹|\?|\d+%).*$", "", cand, flags=re.IGNORECASE).strip()
                    if cand:
                        title = cand
                        break

            # 2. Look for command pattern: "/compare <Name>" or "compare <Name>"
            if not title:
                for line in lines:
                    m_cmd = re.search(
                        r"(?:/compare|compare|/instock|instock|/track|track)\s+([A-Za-z0-9\s\-\.\+]{3,60})",
                        line,
                        re.IGNORECASE,
                    )
                    if m_cmd:
                        cand = m_cmd.group(1).strip(" \t\r\n\"'")
                        # Filter out bot subcommands
                        if cand.lower() not in ("all", "help", "list", "items", "query"):
                            title = cand
                            break

            # 3. Look for prominent e-commerce product title: Line containing known brand + category
            if not title:
                for i, line in enumerate(lines):
                    low = line.lower()
                    if any(term in low for term in _UI_NOISE_TERMS):
                        continue
                    b = extract_brand(line)
                    if b and any(cat in low for cat in CORE_PRODUCT_CATEGORIES):
                        # Join with next line if it continues the product title
                        cand_title = line
                        if i + 1 < len(lines):
                            next_low = lines[i + 1].lower()
                            if not any(term in next_low for term in _UI_NOISE_TERMS) and len(lines[i + 1]) > 3:
                                cand_title = f"{line} {lines[i + 1]}"
                        title = cand_title
                        detected_brand = b
                        break

            # 4. Fallback: Any non-UI line containing a known brand
            if not title:
                for line in lines:
                    low = line.lower()
                    if any(term in low for term in _UI_NOISE_TERMS):
                        continue
                    b = extract_brand(line)
                    if b and len(line) > 5:
                        title = line
                        detected_brand = b
                        break

            if not title:
                return None

            # Clean up title
            title = re.sub(r"\s+", " ", title).strip(" -:|,")
            if not detected_brand:
                detected_brand = extract_brand(title)

            # Detect weight / pack size
            weight_g = extract_weight_in_grams(title) or extract_weight_in_grams(full_text)

            # Detect price from surrounding lines or full text
            for line in lines:
                price_m = re.search(r"(?:₹|\?|rs\.?|inr)\s*([\d,]+)", line, re.IGNORECASE)
                if price_m:
                    p_val = parse_inr_to_paise(price_m.group(1))
                    if p_val and p_val > 5000:  # Minimum ₹50 sanity check
                        price_paise = p_val
                        break

            # Detect store
            low_text = full_text.lower()
            if "hyugalife" in low_text:
                detected_store = "HyugaLife"
            elif "flipkart" in low_text:
                detected_store = "Flipkart"
            elif "amazon" in low_text:
                detected_store = "Amazon"
            elif "nutrabay" in low_text:
                detected_store = "Nutrabay"
            elif "amul" in low_text:
                detected_store = "Amul"
            elif "muscleblaze" in low_text or "healthkart" in low_text:
                detected_store = "MuscleBlaze"

            logger.info(
                "Local offline OCR successfully extracted product from screenshot",
                title=title,
                brand=detected_brand,
                weight_g=weight_g,
                price_paise=price_paise,
                store=detected_store,
            )

            return VisionExtractedProduct(
                title=title,
                brand=detected_brand,
                weight_g=weight_g,
                price_paise=price_paise,
                detected_store=detected_store,
                confidence=0.82,
            )

        except Exception as exc:
            logger.warning("Local OCR extraction failed", error=str(exc))
            return None


# Singleton instance
vision_extractor = VisionExtractor()
