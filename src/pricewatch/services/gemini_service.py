"""Google Gemini AI Service for intelligent query normalization, deal insights, and multimodal vision.

Powered by Gemini 3.8 Flash via generativelanguage REST API.
"""

import base64
import json
from typing import Any, Dict, List, Optional
import httpx

from pricewatch.config import settings
from pricewatch.logging_setup import get_logger

logger = get_logger("gemini_service")

# High-speed Flash Lite model for ultra-fast agentic response and vision
GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest"
GEMINI_FALLBACK_MODEL = "gemini-3.8-flash"


class GeminiService:
    """Orchestrates Gemini AI capabilities across PriceWatch."""

    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)

    async def _call_gemini(self, prompt: str, image_bytes: Optional[bytes] = None, mime_type: str = "image/jpeg") -> Optional[str]:
        """Execute a generateContent call to Gemini with model fallback and error handling."""
        if not self.is_available:
            return None

        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64,
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if text:
                                return text.strip()
                    else:
                        logger.debug("Gemini API non-200 response", model=model, status=resp.status_code)
            except Exception as exc:
                logger.debug("Gemini request encountered exception", model=model, error=str(exc))

        return None

    async def normalize_user_query(self, raw_query: str) -> Optional[Dict[str, Any]]:
        """Normalize messy or typo-laden user search queries into clean structured attributes."""
        if not self.is_available or len(raw_query.strip()) < 3:
            return None

        prompt = (
            f"You are an expert Indian fitness supplement catalog parser. "
            f"Analyze this user search query: \"{raw_query}\"\n"
            f"Extract:\n"
            f"- brand: Brand name (e.g. Nakpro, Nutrabay, MuscleBlaze, Amul, Optimum Nutrition, AS-IT-IS)\n"
            f"- series: Product series/line (e.g. Perform, Biozyme, Impact, Gold Standard, Atom) or null\n"
            f"- category: Supplement category (e.g. whey, creatine, shilajit, peanut_butter, fish_oil)\n"
            f"- weight_g: Package size in grams (e.g. 1000 for 1kg, 20 for 20g, null if not specified)\n"
            f"- flavor: Flavor name or 'unflavoured' or null\n"
            f"- clean_query: Standardized search query string\n"
            f"Output ONLY a valid JSON object matching these keys."
        )

        try:
            res_text = await self._call_gemini(prompt)
            if not res_text:
                return None
            # Strip markdown json codeblock if present
            cleaned = res_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            logger.info("Gemini normalized search query", raw=raw_query, normalized=data.get("clean_query"))
            return data
        except Exception as exc:
            logger.debug("Gemini query normalization error", error=str(exc))
            return None

    async def generate_quick_deal_verdict(self, query_title: str, best_store: str, best_price_inr: float, savings_inr: Optional[float] = None) -> Optional[str]:
        """Generate a crisp, one-line expert buyer verdict for the top deal."""
        if not self.is_available:
            return None

        sav_clause = f" with ₹{savings_inr:,.0f} savings" if savings_inr and savings_inr > 0 else ""
        prompt = (
            f"Provide a 1-sentence concise shopping verdict for an Indian fitness buyer.\n"
            f"Product: {query_title}\n"
            f"Top Deal: {best_store} at ₹{best_price_inr:,.0f}{sav_clause}.\n"
            f"Tone: Crisp, helpful, objective. Max 20 words. No emojis."
        )

        try:
            verdict = await self._call_gemini(prompt)
            return verdict
        except Exception:
            return None


gemini_service = GeminiService()
