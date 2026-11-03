"""Hybrid LLM Router combining Groq (ultra-low latency text) & Gemini (multimodal vision).

Automatically routes tasks to the best provider:
- Groq (qwen/qwen3.8-27b) for sub-300ms search query normalization and deal verdicts.
- Google Gemini (gemini-3.8-flash) for screenshot multimodal extraction and backup.
- Graceful fallbacks so the bot runs 100% reliably even if any API is offline.
"""

import json
from typing import Any, Dict, Optional
import httpx

from pricewatch.config import settings
from pricewatch.logging_setup import get_logger
from pricewatch.services.gemini_service import gemini_service

logger = get_logger("llm_router")

GROQ_DEFAULT_MODEL = "qwen/qwen3.8-27b"


class HybridLLMRouter:
    """Intelligent router selecting the optimal LLM engine for each task."""

    def __init__(self) -> None:
        self.groq_api_key = settings.GROQ_API_KEY

    @property
    def has_groq(self) -> bool:
        key = self.groq_api_key or settings.GROQ_API_KEY
        return bool(key and len(key) > 10)

    @property
    def has_gemini(self) -> bool:
        return gemini_service.is_available

    async def normalize_user_query(self, raw_query: str) -> Optional[Dict[str, Any]]:
        """Normalize user input using Groq for ultra-fast response, with Gemini fallback."""
        if not raw_query or len(raw_query.strip()) < 3:
            return None

        # 1. Try Groq first for sub-300ms speed
        if self.has_groq:
            try:
                norm = await self._normalize_via_groq(raw_query)
                if norm and norm.get("clean_query"):
                    logger.info("Normalized search query via Groq", raw=raw_query, clean=norm.get("clean_query"))
                    return norm
            except Exception as exc:
                logger.debug("Groq normalization encountered exception, falling back to Gemini", error=str(exc))

        # 2. Fallback to Gemini
        if self.has_gemini:
            try:
                return await gemini_service.normalize_user_query(raw_query)
            except Exception as exc:
                logger.debug("Gemini normalization fallback error", error=str(exc))

        return None

    async def _normalize_via_groq(self, raw_query: str) -> Optional[Dict[str, Any]]:
        """Execute structured JSON normalization via Groq's high-speed endpoint."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        prompt = (
            "You are an expert Indian fitness supplement catalog parser. "
            f"User query: \"{raw_query}\"\n"
            "Extract into valid JSON with keys:\n"
            "- brand: Brand name (e.g. Nakpro, Nutrabay, MuscleBlaze, Amul, Optimum Nutrition, AS-IT-IS)\n"
            "- series: Product line (e.g. Perform, Biozyme, Impact, Gold, Atom) or null\n"
            "- category: Supplement category (e.g. whey, creatine, shilajit, peanut_butter, fish_oil)\n"
            "- weight_g: Package weight in grams (e.g. 1000 for 1kg, 20 for 20g, null if not specified)\n"
            "- flavor: Flavor name or 'unflavoured' or null\n"
            "- clean_query: Standardized search query string\n"
            "Output ONLY valid JSON."
        )

        payload = {
            "model": GROQ_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            else:
                logger.debug("Groq non-200 response", status=resp.status_code)
                return None

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Transcribe audio bytes using Groq Whisper (whisper-large-v3-turbo)."""
        if not audio_bytes:
            return None

        if self.has_groq:
            try:
                text = await self._transcribe_via_groq(audio_bytes, filename, prompt)
                if text and text.strip():
                    logger.info("Transcribed audio via Groq Whisper", length=len(text), preview=text[:60])
                    return text.strip()
            except Exception as exc:
                logger.warning("Groq Whisper transcription failed", error=str(exc))

        return None

    async def _transcribe_via_groq(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Call Groq Whisper audio transcriptions endpoint."""
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
        }
        domain_prompt = prompt or (
            "Whey protein, isolate, concentrate, creatine monohydrate, shilajit, "
            "Nakpro, MuscleBlaze, Amul, Asitis, Nutrabay, Optimum Nutrition, "
            "unflavoured, price comparison, budget."
        )

        files = {
            "file": (filename, audio_bytes, "audio/ogg"),
        }
        data = {
            "model": "whisper-large-v3-turbo",
            "prompt": domain_prompt,
            "response_format": "json",
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            if resp.status_code == 200:
                result = resp.json()
                return result.get("text", "")
            else:
                logger.warning("Groq Whisper non-200 response", status=resp.status_code, body=resp.text)
                return None


llm_router = HybridLLMRouter()
