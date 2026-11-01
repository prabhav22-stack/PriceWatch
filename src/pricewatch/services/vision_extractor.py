"""Multimodal Vision & Screenshot Product Extractor.

Extracts product brand, title, variant, weight, and visible price from uploaded photos
or screenshots using Gemini Vision REST API with zero external heavy SDK dependencies.
"""

import base64
import json
import re
from dataclasses import dataclass
from typing import Optional
import httpx

from pricewatch.config import settings
from pricewatch.logging_setup import get_logger

logger = get_logger("vision_extractor")


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

    @staticmethod
    async def extract_from_image_bytes(image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[VisionExtractedProduct]:
        """Send image to Gemini Multimodal Vision API and parse product specs."""
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            logger.info("GEMINI_API_KEY not configured, vision analysis skipped")
            return None

        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

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

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning("Gemini Vision API request failed", status=resp.status_code, text=resp.text[:200])
                    return None

                data = resp.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text_content.strip())

                title = parsed.get("title") or ""
                if not title:
                    return None

                brand = parsed.get("brand")
                variant = parsed.get("variant")
                weight_g = parsed.get("weight_g")
                price_inr = parsed.get("price_inr")
                price_paise = int(round(price_inr * 100)) if price_inr else None
                store = parsed.get("store")

                return VisionExtractedProduct(
                    title=title,
                    brand=brand,
                    variant=variant,
                    weight_g=int(weight_g) if weight_g else None,
                    price_paise=price_paise,
                    detected_store=store,
                    confidence=0.92,
                )
        except Exception as exc:
            logger.warning("Error parsing image with Gemini Vision", error=str(exc))
            return None


# Singleton instance
vision_extractor = VisionExtractor()
